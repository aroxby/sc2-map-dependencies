#!/usr/bin/env python3
import dataclasses
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import sys


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


class ByteArraySerializer(Serializer):
    def __init__(self, length: int, validator=None):
        super().__init__(validator)
        self.length = length

    def deserialize(self, attributes: dict, data: bytes) -> (bytes, int):
        return data[:self.length], self.length


class UInt16Serializer(Serializer):
    length = 2

    def deserialize(self, attributes: dict, data: bytes) -> (int, int):
        return int.from_bytes(data[:self.length], byteorder='little', signed=False), self.length


class UInt32Serializer(UInt16Serializer):
    length = 4


class ZStringSerializer(Serializer):
    def deserialize(self, attributes: dict, data: bytes) -> (str, int):
        mbs, _ = data.split(b'\0', 1)
        return mbs.decode('utf-8'), len(mbs) + 1


class DynamicStringSerializer(Serializer):
    length = 0  # Length isn't known until other fields are deserialized

    def deserialize(self, attributes: dict, data: bytes) -> (str, int):
        mbs = data[:self.length]
        return mbs.decode('utf-8'), len(mbs)


class FixedStringSerializer(DynamicStringSerializer):
    def __init__(self, length: int, validator=None):
        super().__init__(validator)
        self.length = length


class ReverseFixedStringSerializer(FixedStringSerializer):
    def deserialize(self, attributes: dict, data: bytes) -> (str, int):
        value, length = super().deserialize(attributes, data)
        value = value[::-1]
        return value, length


class ListSerializer(Serializer):
    def __init__(self, length_field: dataclasses.Field, element_field: Serializer, validator=None):
        super().__init__(validator)
        self.length_field = length_field
        self.element_field = element_field

    def deserialize(self, attributes: dict, data: bytes) -> (list, int):
        list_length = attributes[self.length_field.name]
        offset = 0
        elements = []

        for _ in range(list_length):
            element, element_length = self.element_field.deserialize(attributes, data[offset:])
            elements.append(element)
            offset += element_length

        return elements, offset


class EncodedLengthSerializer(Serializer):
    def __init__(self, length_field: dataclasses.Field, element_field: Serializer, validator=None):
        super().__init__(validator)
        self.length_field = length_field
        self.element_field = element_field

    def deserialize(self, attributes: dict, data: bytes):
        self.element_field.length = attributes[self.length_field.name]
        return self.element_field.deserialize(attributes, data)


class DataClassSerializer(Serializer):
    def __init__(self, data_class, validator=None):
        super().__init__(validator)
        self.data_class = data_class

    def deserialize(self, attributes: dict, data: bytes):
        return deserialize(self.data_class, data)


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


def file_magic_validator(magic: bytes):
    def validator(value: bytes):
        if value != magic:
            raise ValidationError
    return validator


@dataclass
class DocumentHeaderAttribute:
    key_length: int = serializer_field(UInt16Serializer())
    key: str = serializer_field(EncodedLengthSerializer(key_length, DynamicStringSerializer()))
    locale: int = serializer_field(ReverseFixedStringSerializer(4))
    value_length: int = serializer_field(UInt16Serializer())
    value: str = serializer_field(EncodedLengthSerializer(value_length, DynamicStringSerializer()))


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
    # Number of dependencies
    num_deps: int = serializer_field(UInt32Serializer())
    # Name of dependencies (eg: bnet:Swarm Story (Campaign)/0.0/999,file:Campaigns/SwarmStory.SC2Campaign)
    dependencies: list[str] = serializer_field(ListSerializer(num_deps, ZStringSerializer()))
    # Number of attributes
    num_attribs: int = serializer_field(UInt32Serializer())
    # Instance of attribute (DocumentHeaderAttribute)
    attribs: list[DocumentHeaderAttribute] = serializer_field(
        ListSerializer(num_attribs, DataClassSerializer(DocumentHeaderAttribute)))


def read_document_header(path: Path):
    with open(path, 'rb') as map_file:
        data = map_file.read()

    dh, offset = deserialize(DocumentHeader, data)
    data = data[offset:]

    print('Dependencies:')
    for dependency in dh.dependencies:
        print(dependency)

    print('First and last attributes:')
    print(dh.attribs[0])
    print(dh.attribs[-1])

    print(f'{len(data)} bytes left unread')


def main(argv):
    if len(argv) != 2:
        print(f'Usage: {argv[0]} PATH/TO/MAP.sc2map', file=sys.stderr)
        return 1

    map_path = Path(argv[1])
    read_document_header(map_path / 'documentheader')

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
