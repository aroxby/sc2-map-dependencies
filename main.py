#!/usr/bin/env python3
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from xml.etree import ElementTree

STRING_CODEC = 'cp437'


class ValidationError(Exception):
    pass


class Field(ABC):
    def __init__(self, validator=None):
        self.validator = validator

    def validate(self, value):
        return self.validator(value) if self.validator else None

    @abstractmethod
    def deserialize(self, attributes: dict, data: bytes):
        raise NotImplementedError

    @abstractmethod
    def serialize(self, obj) -> bytes:
        raise NotImplementedError


class ByteArrayField(Field):
    def __init__(self, length: int, validator=None):
        super().__init__(validator)
        self.length = length

    def deserialize(self, attributes: dict, data: bytes) -> (bytes, int):
        return data[:self.length], self.length

    def serialize(self, obj) -> bytes:
        return obj[:self.length]


class UInt16Field(Field):
    length = 2

    def deserialize(self, attributes: dict, data: bytes) -> (int, int):
        return int.from_bytes(data[:self.length], byteorder='little', signed=False), self.length

    def serialize(self, obj) -> bytes:
        return obj.to_bytes(length=self.length, byteorder='little', signed=False)


class UInt32Field(UInt16Field):
    length = 4


class ZStringField(Field):
    def deserialize(self, attributes: dict, data: bytes) -> (str, int):
        mbs, _ = data.split(b'\0', 1)
        return mbs.decode(STRING_CODEC), len(mbs) + 1

    def serialize(self, obj) -> bytes:
        return obj.encode(STRING_CODEC) + b'\0'


class DynamicStringField(Field):
    length = 0  # Length isn't known until other fields are deserialized

    def deserialize(self, attributes: dict, data: bytes) -> (str, int):
        mbs = data[:self.length]
        return mbs.decode(STRING_CODEC), len(mbs)

    def serialize(self, obj) -> bytes:
        return obj.encode(STRING_CODEC)


class FixedStringField(DynamicStringField):
    def __init__(self, length: int, validator=None):
        super().__init__(validator)
        self.length = length


class ReverseFixedStringField(FixedStringField):
    def deserialize(self, attributes: dict, data: bytes) -> (str, int):
        value, length = super().deserialize(attributes, data)
        value = value[::-1]
        return value, length

    def serialize(self, obj) -> bytes:
        return super().serialize(obj[::-1])


class DynamicListField(Field):
    length = 0  # Length isn't known until other fields are deserialized

    def __init__(self, element_field: Field, validator=None):
        super().__init__(validator)
        self.element_field = element_field

    def deserialize(self, attributes: dict, data: bytes) -> (list, int):
        offset = 0
        elements = []

        for _ in range(self.length):
            element, element_length = self.element_field.deserialize(attributes, data[offset:])
            elements.append(element)
            offset += element_length

        return elements, offset

    def serialize(self, obj) -> bytes:
        data = b''
        for element in obj:
            data += self.element_field.serialize(element)
        return data


class EncodedLengthField(Field):
    def __init__(self, length_field: Field, element_field: Field, validator=None):
        super().__init__(validator)
        self.length_field = length_field
        self.element_field = element_field

    def deserialize(self, attributes: dict, data: bytes):
        length, offset = self.length_field.deserialize(attributes, data)
        self.element_field.length = length
        element, element_length = self.element_field.deserialize(attributes, data[offset:])
        return element, offset + element_length

    def serialize(self, obj) -> bytes:
        data = self.length_field.serialize(len(obj))
        data += self.element_field.serialize(obj)
        return data


class SerializerMeta(type):
    @staticmethod
    def _get_fields(attrs: dict) -> dict:
        # TODO: Sort fields? Then use an OrderedDict for deterministic ordering
        fields = {key: value for key, value in attrs.items() if isinstance(value, Field)}
        return fields

    def __new__(cls, name, bases, attrs, **kwds):
        attrs['fields'] = cls._get_fields(attrs)
        return super().__new__(cls, name, bases, attrs)


class Serializer(metaclass=SerializerMeta):
    fields = {}

    # TODO: Drop `attributes`
    def deserialize(self, attributes: dict, data: bytes) -> (dict, int):
        attrs = {}
        offset = 0
        for name, field in self.fields.items():
            attrs[name], field_length = field.deserialize(attributes, data[offset:])
            offset += field_length
        return attrs, offset

    def serialize(self, attrs: dict) -> bytes:
        data = b''
        for name, field in self.fields.items():
            data += field.serialize(attrs[name])
        return data


class SerializerField(Field):
    def __init__(self, serializer: Serializer, validator=None):
        super().__init__(validator)
        self.serializer = serializer

    def deserialize(self, attributes: dict, data: bytes) -> (dict, int):
        return self.serializer.deserialize(attributes, data)

    def serialize(self, obj) -> bytes:
        return self.serializer.serialize(obj)


def file_magic_validator(magic: bytes):
    def validator(value: bytes):
        if value != magic:
            raise ValidationError
    return validator


class DocumentHeaderAttributeSerializer(Serializer):
    key = EncodedLengthField(UInt16Field(), DynamicStringField())
    locale = ReverseFixedStringField(4)
    value = EncodedLengthField(UInt16Field(), DynamicStringField())


class DocumentHeaderSerializer(Serializer):
    # H2CS (StarCraft 2 Header)
    map_magic = ByteArrayField(4, file_magic_validator(b'H2CS'))
    # \x8\0\0\0 (record break?)
    unk1 = ByteArrayField(4)
    # 2S\0\0 (StarCraft 2)
    game_magic = ByteArrayField(4, file_magic_validator(b'2S\0\0'))
    # \x8\0\0\0 (record break?)
    unk2 = ByteArrayField(4)
    # \xe1\x38\x1\0\xe1\x38\x1\0
    unk3 = ByteArrayField(8)
    # ???
    unk4 = ByteArrayField(20)
    # Map dependencies (eg: bnet:Swarm Story (Campaign)/0.0/999,file:Campaigns/SwarmStory.SC2Campaign)
    dependencies = EncodedLengthField(UInt32Field(), DynamicListField(ZStringField()))
    # Map attributes (DocumentHeaderAttribute)
    attribs = EncodedLengthField(
        UInt32Field(), DynamicListField(SerializerField(DocumentHeaderAttributeSerializer()))
    )


@dataclass
class DocumentHeaderAttribute:
    key: str
    locale: int
    value: str


@dataclass
class DocumentHeader:
    map_magic: bytes
    unk1: bytes
    game_magic: bytes
    unk2: bytes
    unk3: bytes
    unk4: bytes
    dependencies: list[str]
    attribs: list[DocumentHeaderAttribute]


def read_document_header(path: Path) -> DocumentHeader:
    with open(path, 'rb') as header_file:
        data = header_file.read()

    attrs, _ = DocumentHeaderSerializer().deserialize({}, data)
    doc_header = DocumentHeader(**attrs)
    # TODO: Would be cool to automatically detect nested classes
    doc_header.attribs = [DocumentHeaderAttribute(**attrib) for attrib in doc_header.attribs]
    return doc_header


def write_document_header(doc_header: DocumentHeader, path: Path):
    attrs = asdict(doc_header)
    data = DocumentHeaderSerializer().serialize(attrs)
    print('Writing disabled for testing')
    # with open(path, 'wb') as header_file:
    #     header_file.write(data)


def do_document_header(document_header_path: Path):
    doc_header = read_document_header(document_header_path)
    write_document_header(doc_header, document_header_path)


def get_or_create_element(parent: ElementTree.Element, name: str) -> ElementTree.Element:
    element = parent.find(name)
    if element is None:
        element = ElementTree.SubElement(parent, name)
    return element


def read_document_info(path: Path) -> ElementTree.ElementTree:
    tree = ElementTree.parse(path)
    # doc_info = tree.getroot()
    # dependencies = get_or_create_element(doc_info, 'Dependencies')
    return tree


def write_document_info(doc_info: ElementTree.ElementTree, path: Path):
    print('Writing disabled for testing')
    # with open(path, 'w', newline='\r\n') as output:
    #     # Why fight with the xml writer when I want this exact declaration?
    #     output.write('<?xml version="1.0" encoding="utf-8"?>\n')
    #     doc_info.write(output, encoding='unicode', xml_declaration=False)
    #     output.write('\n')


def do_document_info(path: Path):
    doc_info = read_document_info(path)
    write_document_info(doc_info, path)


def main(argv):
    if len(argv) != 2:
        print(f'Usage: {argv[0]} PATH/TO/MAP.sc2map', file=sys.stderr)
        return 1

    map_path = Path(argv[1])

    document_header_path = map_path / 'documentheader'
    do_document_header(document_header_path)

    document_info_path = map_path / 'documentinfo'
    do_document_info(document_info_path)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
