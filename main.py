#!/usr/bin/env python3
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from xml.etree import ElementTree

from seri.serializers import Serializer
from seri import fields


type xmlTree = ElementTree.ElementTree[ElementTree.Element[str]]


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


def add_document_header_dependency(doc_header: DocumentHeader, dependency: str):
    if dependency not in doc_header.dependencies:
        doc_header.dependencies.append(dependency)


def do_document_header(document_header_path: Path, deps_to_add: list[str]):
    doc_header = read_document_header(document_header_path)
    for dep in deps_to_add:
        add_document_header_dependency(doc_header, dep)
    write_document_header(doc_header, document_header_path)


def get_or_create_element(parent: ElementTree.Element, name: str) -> ElementTree.Element:
    element = parent.find(name)
    if element is None:
        element = ElementTree.SubElement(parent, name)
    return element


def read_document_info(path: Path) -> xmlTree:
    tree = ElementTree.parse(path)
    return tree


def add_document_info_dependency(tree: xmlTree, dependency: str):
    doc_info = tree.getroot()
    dependencies = get_or_create_element(doc_info, "Dependencies")
    last_sib = None
    for dep in dependencies.findall("Value"):
        if dep.text == dependency:
            return
        last_sib = dep
    if last_sib is not None:
        last_sib.tail = (last_sib.tail or "") + "    "  # Pretty print hack
    new_dep = ElementTree.SubElement(dependencies, "Value")
    new_dep.text = dependency
    new_dep.tail = "\n    "  # Pretty print hack


def write_document_info(doc_info: xmlTree, path: Path):
    with open(path, "w", newline="\r\n") as output:
        # Why fight with the xml writer when I want this exact declaration?
        output.write('<?xml version="1.0" encoding="utf-8"?>\n')
        doc_info.write(output, encoding="unicode", xml_declaration=False)
        output.write("\n")


def do_document_info(path: Path, deps_to_add: list[str]):
    doc_info = read_document_info(path)
    for dep in deps_to_add:
        add_document_info_dependency(doc_info, dep)
    write_document_info(doc_info, path)


def main(argv):
    if len(argv) < 3:
        print(f"Usage: {argv[0]} PATH/TO/MAP.sc2map DEP_TO_ADD [DEP_TO_ADD ...]", file=sys.stderr)
        return 1

    map_path = Path(argv[1])
    dependencies = argv[2:]

    document_header_path = map_path / "DocumentHeader"
    do_document_header(document_header_path, dependencies)

    document_info_path = map_path / "DocumentInfo"
    do_document_info(document_info_path, dependencies)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
