from structures.fields import Field


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

    def deserialize(self, data: bytes) -> (dict, int):
        attrs = {}
        offset = 0
        for name, field in self.fields.items():
            attrs[name], field_length = field.deserialize(data[offset:])
            offset += field_length
        return attrs, offset

    def serialize(self, attrs: dict) -> bytes:
        data = b''
        for name, field in self.fields.items():
            data += field.serialize(attrs[name])
        return data
