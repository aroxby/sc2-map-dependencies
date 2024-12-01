#!/usr/bin/env python3
import dataclasses
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import sys
from xml.etree import ElementTree

STRING_CODEC = 'cp437'


class ValidationError(Exception):
    pass


class Serializer(ABC):
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


class ByteArraySerializer(Serializer):
    def __init__(self, length: int, validator=None):
        super().__init__(validator)
        self.length = length

    def deserialize(self, attributes: dict, data: bytes) -> (bytes, int):
        return data[:self.length], self.length

    def serialize(self, obj) -> bytes:
        return obj[:self.length]


class UInt16Serializer(Serializer):
    length = 2

    def deserialize(self, attributes: dict, data: bytes) -> (int, int):
        return int.from_bytes(data[:self.length], byteorder='little', signed=False), self.length

    def serialize(self, obj) -> bytes:
        return obj.to_bytes(length=self.length, byteorder='little', signed=False)


class UInt32Serializer(UInt16Serializer):
    length = 4


class ZStringSerializer(Serializer):
    def deserialize(self, attributes: dict, data: bytes) -> (str, int):
        mbs, _ = data.split(b'\0', 1)
        return mbs.decode(STRING_CODEC), len(mbs) + 1

    def serialize(self, obj) -> bytes:
        return obj.encode(STRING_CODEC) + b'\0'


class DynamicStringSerializer(Serializer):
    length = 0  # Length isn't known until other fields are deserialized

    def deserialize(self, attributes: dict, data: bytes) -> (str, int):
        mbs = data[:self.length]
        return mbs.decode(STRING_CODEC), len(mbs)

    def serialize(self, obj) -> bytes:
        return obj.encode(STRING_CODEC)


class FixedStringSerializer(DynamicStringSerializer):
    def __init__(self, length: int, validator=None):
        super().__init__(validator)
        self.length = length


class ReverseFixedStringSerializer(FixedStringSerializer):
    def deserialize(self, attributes: dict, data: bytes) -> (str, int):
        value, length = super().deserialize(attributes, data)
        value = value[::-1]
        return value, length

    def serialize(self, obj) -> bytes:
        return super().serialize(obj[::-1])


class DynamicListSerializer(Serializer):
    length = 0  # Length isn't known until other fields are deserialized

    def __init__(self, element_field: Serializer, validator=None):
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


class EncodedLengthSerializer(Serializer):
    def __init__(self, length_field: Serializer, element_field: Serializer, validator=None):
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


class DataClassSerializer(Serializer):
    def __init__(self, data_class, validator=None):
        super().__init__(validator)
        self.data_class = data_class

    def deserialize(self, attributes: dict, data: bytes):
        return deserialize(self.data_class, data)

    def serialize(self, obj) -> bytes:
        return serialize(obj)


def serializer_field(serializer: Serializer) -> dataclasses.Field:
    return dataclasses.field(metadata={'serializer': serializer})


def deserialize(cls, data: bytes, offset: int = 0):
    args = {}
    for fld in dataclasses.fields(cls):
        serializer = fld.metadata.get('serializer', None)

        if serializer is not None:
            args[fld.name], length = serializer.deserialize(args, data[offset:])
            offset += length
            serializer.validate(args[fld.name])
        else:
            raise TypeError(f'Unsupported field {fld}')

    obj = cls(**args)
    return obj, offset


def serialize(obj) -> bytes:
    cls = obj.__class__
    data = b''
    for fld in dataclasses.fields(cls):
        serializer = fld.metadata.get('serializer', None)

        if serializer is not None:
            data += serializer.serialize(getattr(obj, fld.name))
        else:
            raise TypeError(f'Unsupported field {fld}')

    return data


def file_magic_validator(magic: bytes):
    def validator(value: bytes):
        if value != magic:
            raise ValidationError
    return validator


# TODO: Object classes and their serializers are conflated and should be separate objects
@dataclass
class DocumentHeaderAttribute:
    key: str = serializer_field(EncodedLengthSerializer(UInt16Serializer(), DynamicStringSerializer()))
    locale: int = serializer_field(ReverseFixedStringSerializer(4))
    value: str = serializer_field(EncodedLengthSerializer(UInt16Serializer(), DynamicStringSerializer()))


@dataclass
class DocumentHeader:
    # H2CS (StarCraft 2 Header)
    map_magic: bytes = serializer_field(ByteArraySerializer(4, file_magic_validator(b'H2CS')))
    # \x8\0\0\0 (record break?)
    unk1: bytes = serializer_field(ByteArraySerializer(4))
    # 2S\0\0 (StarCraft 2)
    game_magic: bytes = serializer_field(ByteArraySerializer(4, file_magic_validator(b'2S\0\0')))
    # \x8\0\0\0 (record break?)
    unk2: bytes = serializer_field(ByteArraySerializer(4))
    # \xe1\x38\x1\0\xe1\x38\x1\0
    unk3: bytes = serializer_field(ByteArraySerializer(8))
    # ???
    unk4: bytes = serializer_field(ByteArraySerializer(20))
    # Map dependencies (eg: bnet:Swarm Story (Campaign)/0.0/999,file:Campaigns/SwarmStory.SC2Campaign)
    dependencies: list[str] = serializer_field(
        EncodedLengthSerializer(UInt32Serializer(), DynamicListSerializer(ZStringSerializer())))
    # Map attributes (DocumentHeaderAttribute)
    attribs: list[DocumentHeaderAttribute] = serializer_field(
        EncodedLengthSerializer(UInt32Serializer(), DynamicListSerializer(DataClassSerializer(DocumentHeaderAttribute)))
    )


def read_document_header(path: Path) -> DocumentHeader:
    with open(path, 'rb') as header_file:
        data = header_file.read()

    dh, _ = deserialize(DocumentHeader, data)
    return dh


def write_document_header(dh: DocumentHeader):
    data = serialize(dh)
    print('Writing disabled for testing')


def do_document_header(document_header_path: Path):
    dh = read_document_header(document_header_path)
    write_document_header(dh)


def get_or_create_element(parent: ElementTree.Element, name: str) -> ElementTree.Element:
    element = parent.find(name)
    if element is None:
        element = ElementTree.SubElement(parent, name)
    return element


def read_document_info(document_info_path: Path) -> ElementTree.ElementTree:
    tree = ElementTree.parse(document_info_path)
    # doc_info = tree.getroot()
    # dependencies = get_or_create_element(doc_info, 'Dependencies')
    return tree


def write_document_info(doc_info: ElementTree.ElementTree):
    # tree.write(document_info_path)
    print('Writing disabled for testing')


def do_document_info(document_info_path: Path):
    doc_info = read_document_info(document_info_path)
    write_document_info(doc_info)


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
