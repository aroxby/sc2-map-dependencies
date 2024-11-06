#!/usr/bin/env python3
import dataclasses
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import sys


class Field(ABC):
    @abstractmethod
    def deserialize(self, data: bytes):
        raise NotImplementedError


class ByteArrayField(Field):
    def __init__(self, length: int):
        self.length = length

    def deserialize(self, data: bytes) -> (bytes, int):
        return data[:self.length], self.length


class UInt16Field(Field):
    length = 2

    def deserialize(self, data: bytes) -> (int, int):
        return int.from_bytes(data[:self.length], byteorder='little', signed=False), self.length


class UInt32Field(UInt16Field):
    length = 4


class ZStringField(Field):
    def deserialize(self, data: bytes) -> (str, int):
        mbs, _ = data.split(b'\0', 1)
        return mbs.decode('utf-8'), len(mbs) + 1


class ListField:
    def __init__(self, length_field: dataclasses.Field, element_field: Field):
        self.length_field = length_field
        self.element_field = element_field

    def deserialize(self, args: dict, data: bytes, offset: int = 0) -> (list, int):
        list_length = args[self.length_field.name]
        elements = []

        for _ in range(list_length):
            element, element_length = self.element_field.deserialize(data[offset:])
            elements.append(element)
            offset += element_length

        return elements, offset


def serializable_field(serializer: Field) -> dataclasses.Field:
    return dataclasses.field(metadata={'serializer': serializer})


def serializable_list_field(list_field: ListField) -> dataclasses.Field:
    return dataclasses.field(metadata={'list': list_field})


def deserialize(cls, data: bytes, offset: int = 0):
    args = {}
    for fld in dataclasses.fields(cls):
        list_field = fld.metadata.get('list', None)
        serializer = fld.metadata.get('serializer', None)

        if list_field is not None:
            args[fld.name], length = list_field.deserialize(args, data[offset:])
            offset += length
        elif serializer is not None:
            # TODO: If we pass `args` here as well then we could make ListField follow the Field pattern
            args[fld.name], length = serializer.deserialize(data[offset:])
            offset += length
        else:
            raise TypeError(f'Unsupported field {fld}')

    obj = cls(**args)
    return obj, offset


@dataclass
class DocumentHeaderAttribute:
    key_length: int = serializable_field(UInt16Field())
    # FIXME: Not a ZString, fixed by `key_length`
    key: str = serializable_field(ZStringField())
    locale: int = serializable_field(UInt32Field())
    value_length: int = serializable_field(UInt16Field())
    # FIXME: Not a ZString, fixed by `value_length`
    value: str = serializable_field(ZStringField())


@dataclass
class DocumentHeader:
    # TODO: Validate magics as we go to avoid trying to process bad file types
    map_magic: bytes = serializable_field(ByteArrayField(4))   # H2CS (StarCraft 2 Header)
    unk1: bytes = serializable_field(ByteArrayField(4))        # \x8\0\0\0 (record break?)
    game_magic: bytes = serializable_field(ByteArrayField(4))  # 2S\0\0 (StarCraft 2)
    unk2: bytes = serializable_field(ByteArrayField(4))        # \x8\0\0\0 (record break?)
    unk3: bytes = serializable_field(ByteArrayField(8))        # \xe1\x38\x1\0\xe1\x38\x1\0
    unk4: bytes = serializable_field(ByteArrayField(20))       # ?
    num_deps: int = serializable_field(UInt32Field())         # Number of dependencies
    dependencies: str = serializable_list_field(ListField(num_deps, ZStringField()))
    num_attribs: int = serializable_field(UInt32Field())
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


def main(argv):
    if len(argv) != 2:
        print(f'Usage: {argv[0]} PATH/TO/MAP.sc2map', file=sys.stderr)
        return 1

    map_path = Path(argv[1])
    read_document_header(map_path / 'documentheader')

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
