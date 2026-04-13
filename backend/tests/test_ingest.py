from __future__ import annotations

import pytest

from sdsa.ingest import ParseError, parse_sql, parse_txt, parse_upload, sniff_delimiter


# --- CSV dispatcher --------------------------------------------------------

def test_parse_upload_csv():
    raw = b"a,b,c\n1,2,3\n4,5,6\n"
    res = parse_upload("data.csv", raw)
    assert res.format == "csv"
    assert res.df.height == 2
    assert res.df.columns == ["a", "b", "c"]


def test_parse_upload_csv_parses_iso_dates():
    raw = b"id,dob\n1,2026-01-02\n2,2026-03-04\n"
    res = parse_upload("data.csv", raw)
    assert str(res.df["dob"].dtype) == "Date"


def test_parse_upload_unknown_extension():
    with pytest.raises(ParseError):
        parse_upload("data.json", b'{"a": 1}')


def test_parse_upload_empty():
    with pytest.raises(ParseError):
        parse_upload("data.csv", b"")


# --- TXT delimited ---------------------------------------------------------

def test_sniff_delimiter_pipe():
    text = "a|b|c\n1|2|3\n4|5|6\n"
    assert sniff_delimiter(text) == "|"


def test_sniff_delimiter_tab():
    text = "a\tb\tc\n1\t2\t3\n"
    assert sniff_delimiter(text) == "\t"


def test_sniff_delimiter_semicolon():
    text = "a;b;c\n1;2;3\n"
    assert sniff_delimiter(text) == ";"


def test_parse_txt_pipe_delimited():
    text = "timestamp|email|status\n2026-01-01|a@b.co|200\n2026-01-02|c@d.co|500\n"
    res = parse_txt(text)
    assert res.df.height == 2
    assert res.df.columns == ["timestamp", "email", "status"]
    assert res.meta["delimiter"] == "|"
    assert str(res.df["timestamp"].dtype) == "Date"


def test_parse_upload_txt():
    raw = b"a|b|c\n1|2|3\n4|5|6\n"
    res = parse_upload("data.txt", raw)
    assert res.format == "txt"
    assert res.df.height == 2


# --- SQL dump --------------------------------------------------------------

def test_parse_sql_simple_insert():
    sql = """
    INSERT INTO users (id, email, name) VALUES
      (1, 'alice@x.com', 'Alice'),
      (2, 'bob@x.com',   'Bob'),
      (3, 'carol@x.com', 'Carol');
    """
    res = parse_sql(sql)
    assert res.df.height == 3
    assert res.df.columns == ["id", "email", "name"]
    assert res.df["email"].to_list() == ["alice@x.com", "bob@x.com", "carol@x.com"]


def test_parse_sql_handles_nulls_and_numbers():
    sql = "INSERT INTO t (a, b, c) VALUES (1, NULL, 3.5), (2, 'x', NULL);"
    res = parse_sql(sql)
    assert res.df.height == 2
    assert res.df["b"].to_list() == [None, "x"]
    assert res.df["c"].to_list() == [3.5, None]


def test_parse_sql_handles_escaped_quotes():
    sql = "INSERT INTO t (s) VALUES ('O''Brien'), ('a\\'b');"
    res = parse_sql(sql)
    assert res.df["s"].to_list() == ["O'Brien", "a'b"]


def test_parse_sql_strips_comments():
    sql = """
    -- a line comment
    /* a block
       comment */
    INSERT INTO t (a) VALUES (1), (2);
    """
    res = parse_sql(sql)
    assert res.df.height == 2


def test_parse_sql_multi_statement_same_table():
    sql = """
    INSERT INTO t (a, b) VALUES (1, 'x');
    INSERT INTO t (a, b) VALUES (2, 'y'), (3, 'z');
    """
    res = parse_sql(sql)
    assert res.df.height == 3
    assert res.df["a"].to_list() == [1, 2, 3]


def test_parse_sql_rejects_multi_table():
    sql = """
    INSERT INTO a (x) VALUES (1);
    INSERT INTO b (y) VALUES (2);
    """
    with pytest.raises(ParseError):
        parse_sql(sql)


def test_parse_sql_rejects_no_inserts():
    with pytest.raises(ParseError):
        parse_sql("CREATE TABLE t (a INT);")


def test_parse_upload_sql():
    raw = b"INSERT INTO t (a, b) VALUES (1, 'x'), (2, 'y');"
    res = parse_upload("dump.sql", raw)
    assert res.format == "sql"
    assert res.df.height == 2
    assert res.meta["table"] == "t"


def test_parse_sql_rejects_unterminated_row_tuple():
    """Regression: previously, an unterminated VALUES tuple (no closing ')')
    was silently treated as a valid partial row instead of raising."""
    sql = "INSERT INTO t (a, b) VALUES (1, 'open"
    with pytest.raises(ParseError) as exc:
        parse_sql(sql)
    assert "unterminated" in str(exc.value).lower() or "expected ')'" in str(exc.value)
