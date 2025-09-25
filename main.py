#!/usr/bin/env python3
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from xml.etree import ElementTree

from seri.serializers import Serializer
from seri import fields


class DocumentHeaderAttributeSerializer(Serializer):
    key = fields.EncodedLength(fields.UInt16(), fields.DynamicString())
    locale = fields.ReverseFixedString(4)
    value = fields.EncodedLength(fields.UInt16(), fields.DynamicString())


class DocumentHeaderSerializer(Serializer):
    # H2CS (StarCraft 2 Header)
    map_magic = fields.ByteArray(4, fields.file_magic_validator(b"H2CS"))
    # \x8\0\0\0 (record break?)
    unk1 = fields.ByteArray(4)
    # 2S\0\0 (StarCraft 2)
    game_magic = fields.ByteArray(4, fields.file_magic_validator(b"2S\0\0"))
    # \x8\0\0\0 (record break?)
    unk2 = fields.ByteArray(4)
    # \xe1\x38\x1\0\xe1\x38\x1\0 (editor version?)
    unk3 = fields.ByteArray(8)
    # ??? (runtime (game) version?)
    unk4 = fields.ByteArray(20)
    # Map dependencies (eg: bnet:Swarm Story (Campaign)/0.0/999,file:Campaigns/SwarmStory.SC2Campaign)
    dependencies = fields.EncodedLength(fields.UInt32(), fields.DynamicList(fields.ZString()))
    # Map attributes (DocumentHeaderAttribute)
    attribs = fields.EncodedLength(
        fields.UInt32(),
        fields.DynamicList(fields.NestedSerializer(DocumentHeaderAttributeSerializer())),
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
    with open(path, "rb") as header_file:
        data = header_file.read()

    attrs, _ = DocumentHeaderSerializer().deserialize(data)
    doc_header = DocumentHeader(**attrs)
    # TODO: Would be cool to automatically detect nested classes
    doc_header.attribs = [DocumentHeaderAttribute(**attrib) for attrib in doc_header.attribs]
    return doc_header


def write_document_header(doc_header: DocumentHeader, path: Path):
    attrs = asdict(doc_header)
    data = DocumentHeaderSerializer().serialize(attrs)
    with open(path, "wb") as header_file:
        header_file.write(data)


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
    with open(path, "w", newline="\r\n") as output:
        # Why fight with the xml writer when I want this exact declaration?
        output.write('<?xml version="1.0" encoding="utf-8"?>\n')
        doc_info.write(output, encoding="unicode", xml_declaration=False)
        output.write("\n")


def do_document_info(path: Path):
    doc_info = read_document_info(path)
    write_document_info(doc_info, path)


def main(argv):
    if len(argv) != 2:
        print(f"Usage: {argv[0]} PATH/TO/MAP.sc2map", file=sys.stderr)
        return 1

    map_path = Path(argv[1])

    document_header_path = map_path / "documentheader"
    do_document_header(document_header_path)

    document_info_path = map_path / "documentinfo"
    do_document_info(document_info_path)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
