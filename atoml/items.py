import re
import string

from collections.abc import MutableMapping, MutableSequence
from datetime import date, datetime, time, tzinfo
from enum import Enum
from functools import lru_cache
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Union,
    overload,
)

from ._compat import PY38, decode
from ._utils import escape_string


if TYPE_CHECKING:
    from . import container


def item(value, _parent=None, _sort_keys=False):
    from .container import Container

    if isinstance(value, Item):
        return value

    if isinstance(value, bool):
        return Bool(value, Trivia())
    elif isinstance(value, int):
        return Integer(value, Trivia(), str(value))
    elif isinstance(value, float):
        return Float(value, Trivia(), str(value))
    elif isinstance(value, dict):
        val = Table(Container(), Trivia(), False)
        for k, v in sorted(
            value.items(),
            key=lambda i: (isinstance(i[1], dict), i[0] if _sort_keys else 1),
        ):
            val[k] = item(v, _parent=val, _sort_keys=_sort_keys)

        return val
    elif isinstance(value, list):
        if value and isinstance(value[0], dict):
            a = AoT([])
        else:
            a = Array([], Trivia())

        for v in value:
            if isinstance(v, dict):
                table = Table(Container(), Trivia(), True)

                for k, _v in sorted(
                    v.items(),
                    key=lambda i: (isinstance(i[1], dict), i[0] if _sort_keys else 1),
                ):
                    i = item(_v, _sort_keys=_sort_keys)
                    if isinstance(table, InlineTable):
                        i.trivia.trail = ""

                    table[k] = item(i, _sort_keys=_sort_keys)

                v = table

            a.append(v)

        return a
    elif isinstance(value, str):
        escaped = escape_string(value)

        return String(StringType.SLB, decode(value), escaped, Trivia())
    elif isinstance(value, datetime):
        return DateTime(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            Trivia(),
            value.isoformat().replace("+00:00", "Z"),
        )
    elif isinstance(value, date):
        return Date(value.year, value.month, value.day, Trivia(), value.isoformat())
    elif isinstance(value, time):
        return Time(
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            Trivia(),
            value.isoformat(),
        )

    raise ValueError(f"Invalid type {type(value)}")


class StringType(Enum):
    # Single Line Basic
    SLB = '"'
    # Multi Line Basic
    MLB = '"""'
    # Single Line Literal
    SLL = "'"
    # Multi Line Literal
    MLL = "'''"

    @property
    @lru_cache(maxsize=None)
    def unit(self) -> str:
        return self.value[0]

    @lru_cache(maxsize=None)
    def is_basic(self) -> bool:
        return self in {StringType.SLB, StringType.MLB}

    @lru_cache(maxsize=None)
    def is_literal(self) -> bool:
        return self in {StringType.SLL, StringType.MLL}

    @lru_cache(maxsize=None)
    def is_singleline(self) -> bool:
        return self in {StringType.SLB, StringType.SLL}

    @lru_cache(maxsize=None)
    def is_multiline(self) -> bool:
        return self in {StringType.MLB, StringType.MLL}

    @lru_cache(maxsize=None)
    def toggle(self) -> "StringType":
        return {
            StringType.SLB: StringType.MLB,
            StringType.MLB: StringType.SLB,
            StringType.SLL: StringType.MLL,
            StringType.MLL: StringType.SLL,
        }[self]


class BoolType(Enum):
    TRUE = "true"
    FALSE = "false"

    @lru_cache(maxsize=None)
    def __bool__(self):
        return {BoolType.TRUE: True, BoolType.FALSE: False}[self]

    def __iter__(self):
        return iter(self.value)

    def __len__(self):
        return len(self.value)


class Trivia:
    """
    Trivia information (aka metadata).
    """

    def __init__(
        self,
        indent: str = None,
        comment_ws: str = None,
        comment: str = None,
        trail: str = None,
    ) -> None:
        # Whitespace before a value.
        self.indent = indent or ""
        # Whitespace after a value, but before a comment.
        self.comment_ws = comment_ws or ""
        # Comment, starting with # character, or empty string if no comment.
        self.comment = comment or ""
        # Trailing newline.
        if trail is None:
            trail = "\n"

        self.trail = trail


class KeyType(Enum):
    """
    The type of a Key.

    Keys can be bare (unquoted), or quoted using basic ("), or literal (')
    quotes following the same escaping rules as single-line StringType.
    """

    Bare = ""
    Basic = '"'
    Literal = "'"


class Key:
    """
    A key value.
    """

    def __init__(
        self,
        k: str,
        t: Optional[KeyType] = None,
        sep: Optional[str] = None,
        dotted: bool = False,
        original: Optional[str] = None,
    ) -> None:
        if t is None:
            if any(
                [c not in string.ascii_letters + string.digits + "-" + "_" for c in k]
            ):
                t = KeyType.Basic
            else:
                t = KeyType.Bare

        self.t = t
        if sep is None:
            sep = " = "

        self.sep = sep
        self.key = k
        if original is None:
            original = k

        self._original = original

        self._dotted = dotted

    @property
    def delimiter(self) -> str:
        return self.t.value

    def is_dotted(self) -> bool:
        return self._dotted

    def is_bare(self) -> bool:
        return self.t == KeyType.Bare

    def as_string(self) -> str:
        return f"{self.delimiter}{self._original}{self.delimiter}"

    def __hash__(self) -> int:
        return hash(self.key)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Key):
            return self.key == other.key

        return self.key == other

    def __str__(self) -> str:
        return self.as_string()

    def __repr__(self) -> str:
        return f"<Key {self.as_string()}>"


class Item:
    """
    An item within a TOML document.
    """

    def __init__(self, trivia: Trivia) -> None:
        self._trivia = trivia

    @property
    def trivia(self) -> Trivia:
        return self._trivia

    @property
    def discriminant(self) -> int:
        raise NotImplementedError()

    def as_string(self) -> str:
        raise NotImplementedError()

    # Helpers

    def comment(self, comment: str) -> "Item":
        if not comment.strip().startswith("#"):
            comment = "# " + comment

        self._trivia.comment_ws = " "
        self._trivia.comment = comment

        return self

    def indent(self, indent: int) -> "Item":
        if self._trivia.indent.startswith("\n"):
            self._trivia.indent = "\n" + " " * indent
        else:
            self._trivia.indent = " " * indent

        return self

    def is_boolean(self) -> bool:
        return isinstance(self, Bool)

    def is_table(self) -> bool:
        return isinstance(self, Table)

    def is_inline_table(self) -> bool:
        return isinstance(self, InlineTable)

    def is_aot(self) -> bool:
        return isinstance(self, AoT)

    def _getstate(self, protocol=3):
        return (self._trivia,)

    def __reduce__(self):
        return self.__reduce_ex__(2)

    def __reduce_ex__(self, protocol):
        return self.__class__, self._getstate(protocol)


class Whitespace(Item):
    """
    A whitespace literal.
    """

    def __init__(self, s: str, fixed: bool = False) -> None:
        self._s = s
        self._fixed = fixed

    @property
    def s(self) -> str:
        return self._s

    @property
    def value(self) -> str:
        return self._s

    @property
    def trivia(self) -> Trivia:
        raise RuntimeError("Called trivia on a Whitespace variant.")

    @property
    def discriminant(self) -> int:
        return 0

    def is_fixed(self) -> bool:
        return self._fixed

    def as_string(self) -> str:
        return self._s

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {repr(self._s)}>"

    def _getstate(self, protocol=3):
        return self._s, self._fixed


class Comment(Item):
    """
    A comment literal.
    """

    @property
    def discriminant(self) -> int:
        return 1

    def as_string(self) -> str:
        return "{}{}{}".format(
            self._trivia.indent, decode(self._trivia.comment), self._trivia.trail
        )

    def __str__(self) -> str:
        return f"{self._trivia.indent}{decode(self._trivia.comment)}"


class Integer(int, Item):
    """
    An integer literal.
    """

    def __new__(cls, value: int, trivia: Trivia, raw: str) -> "Integer":
        return super().__new__(cls, value)

    def __init__(self, _: int, trivia: Trivia, raw: str) -> None:
        super().__init__(trivia)

        self._raw = raw
        self._sign = False

        if re.match(r"^[+\-]\d+$", raw):
            self._sign = True

    @property
    def discriminant(self) -> int:
        return 2

    @property
    def value(self) -> int:
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other):
        result = super().__add__(other)

        return self._new(result)

    def __radd__(self, other):
        result = super().__radd__(other)

        if isinstance(other, Integer):
            return self._new(result)

        return result

    def __sub__(self, other):
        result = super().__sub__(other)

        return self._new(result)

    def __rsub__(self, other):
        result = super().__rsub__(other)

        if isinstance(other, Integer):
            return self._new(result)

        return result

    def _new(self, result):
        raw = str(result)

        if self._sign:
            sign = "+" if result >= 0 else "-"
            raw = sign + raw

        return Integer(result, self._trivia, raw)

    def _getstate(self, protocol=3):
        return int(self), self._trivia, self._raw


class Float(float, Item):
    """
    A float literal.
    """

    def __new__(cls, value: float, trivia: Trivia, raw: str) -> Integer:
        return super().__new__(cls, value)

    def __init__(self, _: float, trivia: Trivia, raw: str) -> None:
        super().__init__(trivia)

        self._raw = raw
        self._sign = False

        if re.match(r"^[+\-].+$", raw):
            self._sign = True

    @property
    def discriminant(self) -> int:
        return 3

    @property
    def value(self) -> float:
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other):
        result = super().__add__(other)

        return self._new(result)

    def __radd__(self, other):
        result = super().__radd__(other)

        if isinstance(other, Float):
            return self._new(result)

        return result

    def __sub__(self, other):
        result = super().__sub__(other)

        return self._new(result)

    def __rsub__(self, other):
        result = super().__rsub__(other)

        if isinstance(other, Float):
            return self._new(result)

        return result

    def _new(self, result):
        raw = str(result)

        if self._sign:
            sign = "+" if result >= 0 else "-"
            raw = sign + raw

        return Float(result, self._trivia, raw)

    def _getstate(self, protocol=3):
        return float(self), self._trivia, self._raw


class Bool(Item):
    """
    A boolean literal.
    """

    def __init__(self, t: int, trivia: Trivia) -> None:
        super().__init__(trivia)

        self._value = bool(t)

    @property
    def discriminant(self) -> int:
        return 4

    @property
    def value(self) -> bool:
        return self._value

    def as_string(self) -> str:
        return str(self._value).lower()

    def _getstate(self, protocol=3):
        return self._value, self._trivia

    def __bool__(self):
        return self._value

    __nonzero__ = __bool__

    def __eq__(self, other):
        if not isinstance(other, bool):
            return NotImplemented

        return other == self._value

    def __hash__(self):
        return hash(self._value)

    def __repr__(self):
        return repr(self._value)


class DateTime(Item, datetime):
    """
    A datetime literal.
    """

    def __new__(
        cls,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        tzinfo: Optional[tzinfo],
        trivia: Trivia,
        raw: str,
        **kwargs: Any,
    ) -> datetime:
        return datetime.__new__(
            cls,
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            tzinfo=tzinfo,
            **kwargs,
        )

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        tzinfo: Optional[tzinfo],
        trivia: Trivia,
        raw: str,
    ) -> None:
        super().__init__(trivia)

        self._raw = raw

    @property
    def discriminant(self) -> int:
        return 5

    @property
    def value(self) -> datetime:
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other):
        if PY38:
            result = datetime(
                self.year,
                self.month,
                self.day,
                self.hour,
                self.minute,
                self.second,
                self.microsecond,
                self.tzinfo,
            ).__add__(other)
        else:
            result = super().__add__(other)

        return self._new(result)

    def __sub__(self, other):
        if PY38:
            result = datetime(
                self.year,
                self.month,
                self.day,
                self.hour,
                self.minute,
                self.second,
                self.microsecond,
                self.tzinfo,
            ).__sub__(other)
        else:
            result = super().__sub__(other)

        if isinstance(result, datetime):
            result = self._new(result)

        return result

    def _new(self, result):
        raw = result.isoformat()

        return DateTime(
            result.year,
            result.month,
            result.day,
            result.hour,
            result.minute,
            result.second,
            result.microsecond,
            result.tzinfo,
            self._trivia,
            raw,
        )

    def _getstate(self, protocol=3):
        return (
            self.year,
            self.month,
            self.day,
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
            self.tzinfo,
            self._trivia,
            self._raw,
        )


class Date(Item, date):
    """
    A date literal.
    """

    def __new__(cls, year: int, month: int, day: int, *_: Any) -> date:
        return date.__new__(cls, year, month, day)

    def __init__(
        self, year: int, month: int, day: int, trivia: Trivia, raw: str
    ) -> None:
        super().__init__(trivia)

        self._raw = raw

    @property
    def discriminant(self) -> int:
        return 6

    @property
    def value(self) -> date:
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other):
        if PY38:
            result = date(self.year, self.month, self.day).__add__(other)
        else:
            result = super().__add__(other)

        return self._new(result)

    def __sub__(self, other):
        if PY38:
            result = date(self.year, self.month, self.day).__sub__(other)
        else:
            result = super().__sub__(other)

        if isinstance(result, date):
            result = self._new(result)

        return result

    def _new(self, result):
        raw = result.isoformat()

        return Date(result.year, result.month, result.day, self._trivia, raw)

    def _getstate(self, protocol=3):
        return (self.year, self.month, self.day, self._trivia, self._raw)


class Time(Item, time):
    """
    A time literal.
    """

    def __new__(
        cls,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        tzinfo: Optional[tzinfo],
        *_: Any,
    ) -> time:
        return time.__new__(cls, hour, minute, second, microsecond, tzinfo)

    def __init__(
        self,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        tzinfo: Optional[tzinfo],
        trivia: Trivia,
        raw: str,
    ) -> None:
        super().__init__(trivia)

        self._raw = raw

    @property
    def discriminant(self) -> int:
        return 7

    @property
    def value(self) -> time:
        return self

    def as_string(self) -> str:
        return self._raw

    def _getstate(self, protocol: int = 3) -> tuple:
        return (
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
            self.tzinfo,
            self._trivia,
            self._raw,
        )


class Array(Item, MutableSequence, list):
    """
    An array literal
    """

    def __init__(self, value: list, trivia: Trivia, multiline: bool = False) -> None:
        super().__init__(trivia)
        self._index_map: Dict[int, int] = {}
        list.__init__(
            self, [v.value for v in value if not isinstance(v, (Whitespace, Comment))]
        )

        self._value = value
        self._multiline = multiline
        self._reindex()

    @property
    def discriminant(self) -> int:
        return 8

    @property
    def value(self) -> list:
        return self

    def multiline(self, multiline: bool) -> "Array":
        self._multiline = multiline

        return self

    def as_string(self) -> str:
        if not self._multiline:
            return "[{}]".format("".join(v.as_string() for v in self._value))

        s = "[\n" + self.trivia.indent + " " * 4
        s += (",\n" + self.trivia.indent + " " * 4).join(
            v.as_string() for v in self._value if not isinstance(v, Whitespace)
        )
        s += ",\n"
        s += "]"

        return s

    def _reindex(self) -> None:
        self._index_map.clear()
        index = 0
        for i, v in enumerate(self._value):
            if isinstance(v, (Whitespace, Comment)):
                continue
            self._index_map[index] = i
            index += 1

    def clear(self) -> None:
        list.clear(self)

        self._value.clear()
        self._index_map.clear()

    def __len__(self) -> int:
        return list.__len__(self)

    def __getitem__(self, key: Union[int, slice]) -> Any:
        return list.__getitem__(self, key)

    def __setitem__(self, key: Union[int, slice], value: Any) -> Any:
        it = item(value)
        list.__setitem__(self, key, it.value)
        if isinstance(key, slice):
            raise ValueError("slice assignment is not supported")
        if key < 0:
            key += len(self)
        self._value[self._index_map[key]] = it

    def insert(self, pos: int, value: Any) -> None:
        it = item(value)
        length = len(self)
        if not isinstance(it, (Comment, Whitespace)):
            list.insert(self, pos, it.value)
        if pos < 0:
            pos += length

        if 0 <= pos < length:
            try:
                idx = self._index_map[pos]
            except KeyError:
                raise IndexError("list index out of range")
        else:
            idx = len(self._value) if pos >= length else pos
        items = [it]
        if self._value and idx < len(self._value):
            items.append(Whitespace(", "))
        elif self._value and idx >= len(self._value):
            # Append to the last
            i = len(self._value) - 1
            while i and isinstance(self._value[i], (Comment, Whitespace)):
                if (
                    isinstance(self._value[i], Whitespace)
                    and self._value[i].s.strip() == ","
                ):
                    break
                i -= 1
            else:
                items.insert(0, Whitespace(", "))
        self._value[idx:idx] = items

        self._reindex()

    def __delitem__(self, key: Union[int, slice]):
        length = len(self)
        list.__delitem__(self, key)

        def get_indice_to_remove(idx: int) -> Iterable[int]:
            try:
                real_idx = self._index_map[idx]
            except KeyError:
                raise IndexError("list index out of range")
            yield real_idx
            for i in range(real_idx + 1, len(self._value)):
                if isinstance(self._value[i], Whitespace):
                    yield i

        indexes = set()
        if isinstance(key, slice):
            for idx in range(key.start or 0, key.end or length, key.step or 1):
                indexes.update(get_indice_to_remove(idx))
        else:
            indexes.update(get_indice_to_remove(length + key if key < 0 else key))
        for i in sorted(indexes, reverse=True):
            del self._value[i]
        while self._value and isinstance(self._value[-1], Whitespace):
            self._value.pop()
        self._reindex()

    def __str__(self):
        return str(
            [v.value for v in self._value if not isinstance(v, (Whitespace, Comment))]
        )

    def _getstate(self, protocol=3):
        return self._value, self._trivia


class Table(Item, MutableMapping, dict):
    """
    A table literal.
    """

    def __init__(
        self,
        value: "container.Container",
        trivia: Trivia,
        is_aot_element: bool,
        is_super_table: bool = False,
        name: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> None:
        super().__init__(trivia)

        self.name = name
        self.display_name = display_name
        self._value = value
        self._is_aot_element = is_aot_element
        self._is_super_table = is_super_table

        for k, v in self._value.body:
            if k is not None:
                dict.__setitem__(self, k.key, v)

    @property
    def value(self) -> "container.Container":
        return self._value

    @property
    def discriminant(self) -> int:
        return 9

    def add(self, key: Union[Key, Item, str], item: Any = None) -> Item:
        if item is None:
            if not isinstance(key, (Comment, Whitespace)):
                raise ValueError(
                    "Non comment/whitespace items must have an associated key"
                )

            key, item = None, key

        return self.append(key, item)

    def append(self, key: Union[Key, str], _item: Any) -> "Table":
        """
        Appends a (key, item) to the table.
        """
        if not isinstance(_item, Item):
            _item = item(_item)

        self._value.append(key, _item)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            dict.__setitem__(self, key, _item)

        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if not m:
            return self

        indent = m.group(1)

        if not isinstance(_item, Whitespace):
            m = re.match("(?s)^([^ ]*)(.*)$", _item.trivia.indent)
            if not m:
                _item.trivia.indent = indent
            else:
                _item.trivia.indent = m.group(1) + indent + m.group(2)

        return self

    def raw_append(self, key: Union[Key, str], _item: Any) -> "Table":
        if not isinstance(_item, Item):
            _item = item(_item)

        self._value.append(key, _item)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            dict.__setitem__(self, key, _item)

        return self

    def remove(self, key: Union[Key, str]) -> "Table":
        self._value.remove(key)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            dict.__delitem__(self, key)

        return self

    def is_aot_element(self) -> bool:
        return self._is_aot_element

    def is_super_table(self) -> bool:
        return self._is_super_table

    def as_string(self) -> str:
        return self._value.as_string()

    # Helpers

    def indent(self, indent: int) -> "Table":
        super().indent(indent)

        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if not m:
            indent = ""
        else:
            indent = m.group(1)

        for _, item in self._value.body:
            if not isinstance(item, Whitespace):
                item.trivia.indent = indent + item.trivia.indent

        return self

    def __iter__(self) -> Iterator[str]:
        return iter(self._value)

    def __len__(self) -> int:
        return len(self._value)

    def __getitem__(self, key: Union[Key, str]) -> Item:
        return self._value[key]

    def __setitem__(self, key: Union[Key, str], value: Any) -> None:
        if not isinstance(value, Item):
            value = item(value)

        is_replace = key in self
        self._value[key] = value

        if key is not None:
            dict.__setitem__(self, key, value)

        if is_replace:
            return
        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if not m:
            return

        indent = m.group(1)

        if not isinstance(value, Whitespace):
            m = re.match("(?s)^([^ ]*)(.*)$", value.trivia.indent)
            if not m:
                value.trivia.indent = indent
            else:
                value.trivia.indent = m.group(1) + indent + m.group(2)

    def __delitem__(self, key: Union[Key, str]) -> None:
        self.remove(key)

    def setdefault(self, key: Union[Key, str], default: Any) -> Any:
        super().setdefault(key, default=default)
        return self[key]

    def __str__(self):
        return str(self.value)

    def __repr__(self) -> str:
        return repr(self.value)

    def _getstate(self, protocol: int = 3) -> tuple:
        return (
            self._value,
            self._trivia,
            self._is_aot_element,
            self._is_super_table,
            self.name,
            self.display_name,
        )


class InlineTable(Item, MutableMapping, dict):
    """
    An inline table literal.
    """

    def __init__(
        self, value: "container.Container", trivia: Trivia, new: bool = False
    ) -> None:
        super().__init__(trivia)

        self._value = value
        self._new = new

        for k, v in self._value.body:
            if k is not None:
                dict.__setitem__(self, k.key, v)

    @property
    def discriminant(self) -> int:
        return 10

    @property
    def value(self) -> dict:
        return self._value

    def append(self, key: Union[Key, str], _item: Any) -> "InlineTable":
        """
        Appends a (key, item) to the table.
        """
        if not isinstance(_item, Item):
            _item = item(_item)

        if not isinstance(_item, (Whitespace, Comment)):
            if not _item.trivia.indent and len(self._value) > 0 and not self._new:
                _item.trivia.indent = " "
            if _item.trivia.comment:
                _item.trivia.comment = ""

        self._value.append(key, _item)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            dict.__setitem__(self, key, _item)

        return self

    def remove(self, key: Union[Key, str]) -> "InlineTable":
        self._value.remove(key)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            dict.__delitem__(self, key)

        return self

    def as_string(self) -> str:
        buf = "{"
        for i, (k, v) in enumerate(self._value.body):
            if k is None:
                if i == len(self._value.body) - 1:
                    if self._new:
                        buf = buf.rstrip(", ")
                    else:
                        buf = buf.rstrip(",")

                buf += v.as_string()

                continue

            buf += "{}{}{}{}{}{}".format(
                v.trivia.indent,
                k.as_string() + ("." if k.is_dotted() else ""),
                k.sep,
                v.as_string(),
                v.trivia.comment,
                v.trivia.trail.replace("\n", ""),
            )

            if i != len(self._value.body) - 1:
                buf += ","
                if self._new:
                    buf += " "

        buf += "}"

        return buf

    def __getitem__(self, key: Union[Key, str]) -> Item:
        return self._value[key]

    def __setitem__(self, key: Union[Key, str], value: Any) -> None:
        if not isinstance(value, Item):
            value = item(value)

        self._value[key] = value

        if key is not None:
            dict.__setitem__(self, key, value)
        if value.trivia.comment:
            value.trivia.comment = ""

        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if not m:
            return

        indent = m.group(1)

        if not isinstance(value, Whitespace):
            m = re.match("(?s)^([^ ]*)(.*)$", value.trivia.indent)
            if not m:
                value.trivia.indent = indent
            else:
                value.trivia.indent = m.group(1) + indent + m.group(2)

    def __delitem__(self, key: Union[Key, str]) -> None:
        self.remove(key)

    def __len__(self) -> int:
        return len(self._value)

    def __iter__(self) -> Iterator[str]:
        return iter(self._value)

    def __repr__(self) -> str:
        return repr(self.value)

    def setdefault(self, key: Union[Key, str], default: Any) -> Any:
        super().setdefault(key, default=default)
        return self[key]

    def _getstate(self, protocol: int = 3) -> tuple:
        return (self._value, self._trivia)


class String(str, Item):
    """
    A string literal.
    """

    def __new__(cls, t, value, original, trivia):
        return super().__new__(cls, value)

    def __init__(self, t: StringType, _: str, original: str, trivia: Trivia) -> None:
        super().__init__(trivia)

        self._t = t
        self._original = original

    @property
    def discriminant(self) -> int:
        return 11

    @property
    def value(self) -> str:
        return self

    def as_string(self) -> str:
        return f"{self._t.value}{decode(self._original)}{self._t.value}"

    def __add__(self, other):
        result = super().__add__(other)

        return self._new(result)

    def __sub__(self, other):
        result = super().__sub__(other)

        return self._new(result)

    def _new(self, result):
        return String(self._t, result, result, self._trivia)

    def _getstate(self, protocol=3):
        return self._t, str(self), self._original, self._trivia


class AoT(Item, MutableSequence, list):
    """
    An array of table literal
    """

    def __init__(
        self, body: List[Table], name: Optional[str] = None, parsed: bool = False
    ) -> None:
        self.name = name
        self._body: List[Table] = []
        self._parsed = parsed

        super().__init__(Trivia(trail=""))

        for table in body:
            self.append(table)

    @property
    def body(self) -> List[Table]:
        return self._body

    @property
    def discriminant(self) -> int:
        return 12

    @property
    def value(self) -> List[Dict[Any, Any]]:
        return [v.value for v in self._body]

    def __len__(self) -> int:
        return len(self._body)

    @overload
    def __getitem__(self, key: slice) -> List[Table]:
        ...

    @overload
    def __getitem__(self, key: int) -> Table:
        ...

    def __getitem__(self, key):
        return self._body[key]

    def __setitem__(self, key: Union[slice, int], value: Any) -> None:
        raise NotImplementedError

    def __delitem__(self, key: Union[slice, int]) -> None:
        del self._body[key]
        list.__delitem__(self, key)

    def insert(self, index: int, value: Table) -> None:
        if not isinstance(value, Table):
            raise ValueError(f"Unsupported insert value type: {type(value)}")
        length = len(self)
        if index < 0:
            index += length
        if index < 0:
            index = 0
        elif index >= length:
            index = length
        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if m:
            indent = m.group(1)

            m = re.match("(?s)^([^ ]*)(.*)$", value.trivia.indent)
            if not m:
                value.trivia.indent = indent
            else:
                value.trivia.indent = m.group(1) + indent + m.group(2)
        prev_table = self._body[index - 1] if 0 < index and length else None
        next_table = self._body[index + 1] if index < length - 1 else None
        if not self._parsed:
            if prev_table and "\n" not in value.trivia.indent:
                value.trivia.indent = "\n" + value.trivia.indent
            if next_table and "\n" not in next_table.trivia.indent:
                next_table.trivia.indent = "\n" + next_table.trivia.indent
        self._body.insert(index, value)
        list.insert(self, index, value)

    def as_string(self) -> str:
        b = ""
        for table in self._body:
            b += table.as_string()

        return b

    def __repr__(self) -> str:
        return f"<AoT {self.value}>"

    def _getstate(self, protocol=3):
        return self._body, self.name, self._parsed


class Null(Item):
    """
    A null item.
    """

    def __init__(self) -> None:
        pass

    @property
    def discriminant(self) -> int:
        return -1

    @property
    def value(self) -> None:
        return None

    def as_string(self) -> str:
        return ""

    def _getstate(self, protocol=3):
        return tuple()
