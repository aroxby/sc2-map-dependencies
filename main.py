#!/usr/bin/env python3
from dataclasses import dataclass, Field, field, fields
from pathlib import Path
import sys


def serializable_field(size: int) -> Field:
    return field(metadata={'size': size})


def deserialize(data: bytes, cls, offset: int = 0):
    args = {}
    for fld in fields(cls):
        args[fld.name] = fld.type()
        size = fld.metadata.get('size', None)
        if size is not None:
            value_bytes = data[offset: offset + size]
            offset += size

            if isinstance(args[fld.name], bytes):
                args[fld.name] = value_bytes[:]
            elif isinstance(args[fld.name], int):
                args[fld.name] = fld.type.from_bytes(value_bytes, 'little', signed=False)
            else:
                raise TypeError(f'No deserialize available for {fld.type}')

    obj = cls(**args)
    return obj, offset


@dataclass
class DocumentHeaderData:
    map_magic: bytes = serializable_field(4)    # H2CS (StarCraft 2 Header)
    unk1: bytes  = serializable_field(4)        # \x8\0\0\0 (record break?)
    game_magic: bytes  = serializable_field(4)  # 2S\0\0 (StarCraft 2)
    unk2: bytes  = serializable_field(4)        # \x8\0\0\0 (record break?)
    unk3: bytes  = serializable_field(8)        # \xe1\x38\x1\0\xe1\x38\x1\0
    unk4: bytes  = serializable_field(20)       # ?
    num_deps: int = serializable_field(4)       # Number of dependencies
    # TODO: Maybe we could chain values of variable size?
    # dependencies: list[str] = scanner(value.split, (b'\0',), num_deps)
    # Can scanner types have size? ValueError: cannot specify both size and scanner


@dataclass
class DocumentHeaderDataAttributeKey:
    key_length: int  = serializable_field(2)
    key: str


@dataclass
class DocumentHeaderDataAttributeValue:
    locale: int = serializable_field(4)
    value_length: int = serializable_field(2)
    value: str


class DocumentHeader:
    header: DocumentHeaderData
    dependencies: list[str]  # null-terminated in file
    num_atrribs: int  # 4 bytes
    first_key: list[DocumentHeaderDataAttributeKey]
    first_value: list[DocumentHeaderDataAttributeValue]
    # ...


def read_document_header(path: Path):
    with open(path, 'rb') as map_file:
        data = map_file.read()

    dc, offset = deserialize(data, DocumentHeaderData)
    data = data[offset:]

    print('magic1', dc.map_magic)
    print('magic2', dc.game_magic)

    dependencies = []
    for _ in range(dc.num_deps):
        dep_ascii, data = data.split(b'\0', 1)
        dependencies.append(dep_ascii.decode('utf-8'))
    print(dependencies)

    num_atrribs_bytes = data[:4]
    offset +=4
    num_atrribs = int.from_bytes(num_atrribs_bytes, 'little', signed=False)
    print(num_atrribs)


def main(argv):
    if len(argv) != 2:
        print(f'Usage: {argv[0]} PATH/TO/MAP.sc2map', file=sys.stderr)
        return 1

    map_path = Path(argv[1])
    read_document_header(map_path / 'documentheader')

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))