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


class EncodedLengthField(Serializer):
    def __init__(self, length_field: dataclasses.Field, element_field: Serializer, validator=None):
        super().__init__(validator)
        self.length_field = length_field
        self.element_field = element_field

    def deserialize(self, attributes: dict, data: bytes, offset: int = 0) -> (list, int):
        self.element_field.length = attributes[self.length_field.name]
        element, element_length = self.element_field.deserialize(attributes, data[offset:])
        offset += element_length
        return element, offset


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
    key: str = serializer_field(EncodedLengthField(key_length, DynamicStringSerializer()))
    # Same as used in WOW
    # | `EN_US` | 1701729619 (0x656E5553) |  |
    # https://github.com/gtker/wow_messages/blob/b55fe18/wowm_language/src/docs/locale.md?plain=1#L33
    locale: int = serializer_field(UInt32Serializer())
    value_length: int = serializer_field(UInt16Serializer())
    value: str = serializer_field(EncodedLengthField(value_length, DynamicStringSerializer()))


@dataclass
class DocumentHeader:
    # TODO: Validate magics as we go to avoid trying to process bad file types
    map_magic: bytes = serializer_field(ByteArraySerializer(4, file_magic_validator(b'H2CS')))   # H2CS (StarCraft 2 Header)
    unk1: bytes = serializer_field(ByteArraySerializer(4))        # \x8\0\0\0 (record break?)
    game_magic: bytes = serializer_field(ByteArraySerializer(4, file_magic_validator(b'2S\0\0')))  # 2S\0\0 (StarCraft 2)
    unk2: bytes = serializer_field(ByteArraySerializer(4))        # \x8\0\0\0 (record break?)
    unk3: bytes = serializer_field(ByteArraySerializer(8))        # \xe1\x38\x1\0\xe1\x38\x1\0
    unk4: bytes = serializer_field(ByteArraySerializer(20))       # ?
    num_deps: int = serializer_field(UInt32Serializer())         # Number of dependencies
    dependencies: str = serializer_field(ListSerializer(num_deps, ZStringSerializer()))
    num_attribs: int = serializer_field(UInt32Serializer())
    # TODO: Create nestable dataclass field so that `DocumentHeaderAttribute`s can also live here


def read_document_header(path: Path):
    with open(path, 'rb') as map_file:
        data = map_file.read()

    dh, offset = deserialize(DocumentHeader, data)
    data = data[offset:]

    print('magic1', dh.map_magic)
    print('magic2', dh.game_magic)
    print('depend', dh.dependencies)
    print('attribs', dh.num_attribs)

    dha, offset = deserialize(DocumentHeaderAttribute, data)
    data = data[offset:]
    print('First attribute:')
    print(dha)


def main(argv):
    if len(argv) != 2:
        print(f'Usage: {argv[0]} PATH/TO/MAP.sc2map', file=sys.stderr)
        return 1

    map_path = Path(argv[1])
    read_document_header(map_path / 'documentheader')

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
