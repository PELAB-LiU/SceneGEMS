from abc import ABC
from typing import Any, Dict, Type, Union, get_args, get_origin


def is_optional_type(attribute_type: Type):
    # Check if the class is an Optional (or Union with None)
    return get_origin(attribute_type) is Union and type(None) in get_args(attribute_type)


def get_inner_type(attribute_type: Type):
    if is_optional_type(attribute_type):
        # Extract the non-None type(s) from the Optional
        return [arg for arg in get_args(attribute_type) if arg is not type(None)][0]
    raise ValueError("Provided type is not Optional")


class Serializable(ABC):
    def to_dict(self):
        """Convert the object into a dictionary."""
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Serializable):  # Handle nested Serializable objects
                result[key] = value.to_dict()
            else:  # Handle primitive types
                result[key] = value
        return result

    @classmethod
    def from_dict(cls: Type["Serializable"], data: Dict[str, Any]) -> "Serializable":
        """
        Creates an instance of the class from a dictionary representation,
        handling nested serializable attributes, lists, and dictionaries.
        """
        obj = cls.__new__(cls)
        for attr, value in data.items():
            attr_type = cls.get_type_by_annotation(attr)
            if value is None or not (isinstance(attr_type, type) and issubclass(attr_type, Serializable)):
                setattr(obj, attr, value)
            else:
                setattr(obj, attr, attr_type.from_dict(value))
        return obj

    @classmethod
    def get_type_by_annotation(cls: Type["Serializable"], attribute_name) -> Type:
        annotations = cls.__annotations__
        if attribute_name not in annotations:
            raise ValueError(f"Attribute '{attribute_name}' is not annotated in the class.")

        # Get the type annotation of the attribute
        attr_type = annotations[attribute_name]

        if is_optional_type(attr_type):
            attr_type = get_inner_type(attr_type)
        return attr_type
