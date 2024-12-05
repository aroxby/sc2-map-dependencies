from abc import ABC, abstractmethod

STRING_CODEC = 'cp437'


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


class SerializerField(Field):
    def __init__(self, serializer: 'Serializer', validator=None):
        super().__init__(validator)
        self.serializer = serializer

    def deserialize(self, attributes: dict, data: bytes) -> (dict, int):
        return self.serializer.deserialize(attributes, data)

    def serialize(self, obj) -> bytes:
        return self.serializer.serialize(obj)


class ValidationError(Exception):
    pass


def file_magic_validator(magic: bytes):
    def validator(value: bytes):
        if value != magic:
            raise ValidationError
    return validator
