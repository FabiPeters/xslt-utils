"""Tests for xslt_utils. Run with: python -m unittest -v"""

import os
import tempfile
import unittest

from xslt_utils import PySaxonApiError, PyXdmNode, read_xml, transform, write_xml

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<books><book year="1808">Faust</book><book year="1922">Ulysses</book></books>
"""

LIST_XSL = """<xsl:stylesheet version="3.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:param name="label" select="'none'"/>
  <xsl:template match="/books">
    <list label="{$label}"><xsl:for-each select="book"><item><xsl:value-of select="upper-case(.)"/></item></xsl:for-each></list>
  </xsl:template>
</xsl:stylesheet>
"""

# Global variables of every common kind: a constant, one derived from a
# parameter, one that reads the source document (needs the global context
# item), and one built from another global variable.
GLOBALS_XSL = """<xsl:stylesheet version="3.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="text"/>
  <xsl:param name="prefix" select="'#'"/>
  <xsl:variable name="title" select="'Library'"/>
  <xsl:variable name="marker" select="$prefix || $prefix"/>
  <xsl:variable name="books" select="/books/book"/>
  <xsl:variable name="summary" select="$title || ': ' || count($books) || ' books'"/>
  <xsl:template match="/">
    <xsl:value-of select="$marker, $summary, string-join($books, ','), min($books/@year)" separator="|"/>
  </xsl:template>
</xsl:stylesheet>
"""
GLOBALS_RESULT = "##|Library: 2 books|Faust,Ulysses|1808"

IDENTITY_XSL = """<xsl:stylesheet version="3.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:mode on-no-match="shallow-copy"/>
</xsl:stylesheet>
"""

DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>'


def sheet(body):
    return f'<xsl:stylesheet version="3.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">{body}</xsl:stylesheet>'


class TestCase(unittest.TestCase):
    def setUp(self):
        # On Windows, Saxon keeps the output file of a failed write open until the process ends.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = self._tmp.name
        self.xml_path = self._write("in.xml", SAMPLE_XML)
        self.doc = read_xml(self.xml_path)
        self.list_xsl = self._write("list.xsl", LIST_XSL)
        self.globals_xsl = self._write("globals.xsl", GLOBALS_XSL)
        self.identity_xsl = self._write("identity.xsl", IDENTITY_XSL)
        self.out = os.path.join(self.dir, "out.xml")

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, content):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _read_bytes(self, path):
        with open(path, "rb") as f:
            return f.read()

    def _make_lookup_setup(self):
        """Source in data/ refers to lookup.xml; a decoy lookup.xml sits in the temp root."""
        os.mkdir(os.path.join(self.dir, "data"))
        source = self._write(os.path.join("data", "input.xml"), '<root><ref href="lookup.xml"/></root>')
        self._write(os.path.join("data", "lookup.xml"), "<lookup>right</lookup>")
        self._write("lookup.xml", "<lookup>wrong</lookup>")
        xsl = self._write("lookup.xsl", sheet(
            '<xsl:output method="text"/><xsl:template match="/">'
            '<xsl:value-of select="document(root/ref/@href)"/></xsl:template>'))
        return source, xsl


class ReadXmlTest(TestCase):
    def test_returns_node(self):
        self.assertIsInstance(self.doc, PyXdmNode)
        self.assertIn('<book year="1808">Faust</book>', self.doc.to_string())

    def test_missing_file_raises(self):
        with self.assertRaises(PySaxonApiError):
            read_xml(os.path.join(self.dir, "missing.xml"))


class TransformToNodeTest(TestCase):
    def test_returns_node(self):
        node = transform(self.doc, self.list_xsl)
        self.assertIsInstance(node, PyXdmNode)
        self.assertEqual(node.to_string(), '<list label="none">\n   <item>FAUST</item>\n   <item>ULYSSES</item>\n</list>')

    def test_params(self):
        self.assertIn('label="Klassiker"', transform(self.doc, self.list_xsl, {"label": "Klassiker"}).to_string())

    def test_param_values_are_converted_to_strings(self):
        self.assertIn('label="42"', transform(self.doc, self.list_xsl, {"label": 42}).to_string())

    def test_chaining(self):
        step = transform(self.doc, self.list_xsl)
        step = transform(step, self.identity_xsl)
        self.assertIn("<item>ULYSSES</item>", step.to_string())

    def test_input_node_is_reusable(self):
        first = transform(self.doc, self.list_xsl).to_string()
        self.assertEqual(transform(self.doc, self.list_xsl).to_string(), first)

    def test_global_variables(self):
        self.assertEqual(transform(self.doc, self.globals_xsl).string_value, GLOBALS_RESULT)

    def test_global_variable_depending_on_param(self):
        node = transform(self.doc, self.globals_xsl, {"prefix": "*"})
        self.assertTrue(node.string_value.startswith("**|"), node.string_value)

    def test_global_variables_in_chain(self):
        step = transform(self.doc, self.identity_xsl)
        self.assertEqual(transform(step, self.globals_xsl).string_value, GLOBALS_RESULT)

    def test_empty_output(self):
        empty = self._write("empty.xsl", sheet('<xsl:template match="/"/>'))
        node = transform(self.doc, empty)
        self.assertIsInstance(node, PyXdmNode)
        self.assertEqual(node.to_string(), "")

    def test_keeps_location_for_relative_document_paths(self):
        source, xsl = self._make_lookup_setup()
        self.assertEqual(transform(read_xml(source), xsl).string_value, "right")

    def test_keeps_location_through_chain(self):
        source, xsl = self._make_lookup_setup()
        step = transform(read_xml(source), self.identity_xsl)
        step = transform(step, self.identity_xsl)
        self.assertEqual(transform(step, xsl).string_value, "right")

    def test_result_document_resolves_next_to_input(self):
        os.mkdir(os.path.join(self.dir, "src"))
        source = self._write(os.path.join("src", "in.xml"), "<a/>")
        xsl = self._write("side.xsl", sheet(
            '<xsl:template match="/"><xsl:result-document href="side.xml"><s/></xsl:result-document><main/></xsl:template>'))
        transform(read_xml(source), xsl)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "src", "side.xml")))

    def test_string_input_is_rejected(self):
        with self.assertRaises(TypeError):
            transform(SAMPLE_XML, self.list_xsl)

    def test_missing_stylesheet_raises(self):
        with self.assertRaises(PySaxonApiError):
            transform(self.doc, os.path.join(self.dir, "missing.xsl"))

    def test_invalid_stylesheet_raises(self):
        broken = self._write("broken.xsl", sheet("<xsl:nope/>"))
        with self.assertRaises(PySaxonApiError):
            transform(self.doc, broken)

    def test_dynamic_error_raises(self):
        failing = self._write("fail.xsl", sheet(
            '<xsl:template match="/"><xsl:sequence select="error()"/></xsl:template>'))
        with self.assertRaises(PySaxonApiError):
            transform(self.doc, failing)


class TransformToFileTest(TestCase):
    def _output_of(self, body):
        """Run a stylesheet with `body` to a file and return the bytes written."""
        xsl = self._write("case.xsl", sheet(body))
        self.assertIsNone(transform(self.doc, xsl, output_file=self.out))
        return self._read_bytes(self.out)

    def test_params(self):
        transform(self.doc, self.list_xsl, {"label": "x"}, output_file=self.out)
        self.assertEqual(self._read_bytes(self.out),
                         DECLARATION + b'<list label="x"><item>FAUST</item><item>ULYSSES</item></list>')

    def test_global_variables(self):
        transform(self.doc, self.globals_xsl, output_file=self.out)
        self.assertEqual(self._read_bytes(self.out), GLOBALS_RESULT.encode())

    def test_location_after_chain(self):
        source, xsl = self._make_lookup_setup()
        step = transform(read_xml(source), self.identity_xsl)
        transform(step, xsl, output_file=self.out)
        self.assertEqual(self._read_bytes(self.out), b"right")

    def test_indent_with_lf_line_endings(self):
        data = self._output_of('<xsl:output indent="yes"/><xsl:template match="/"><o><x/></o></xsl:template>')
        self.assertEqual(data, DECLARATION + b"\n<o>\n   <x/>\n</o>\n")

    def test_omit_xml_declaration(self):
        data = self._output_of('<xsl:output omit-xml-declaration="yes"/><xsl:template match="/"><o/></xsl:template>')
        self.assertEqual(data, b"<o/>")

    def test_encoding(self):
        data = self._output_of('<xsl:output encoding="ISO-8859-1"/><xsl:template match="/"><o>&#228; &#8364;</o></xsl:template>')
        self.assertEqual(data, b'<?xml version="1.0" encoding="ISO-8859-1"?><o>\xe4 &#x20ac;</o>')
        self.assertIn("<o>ä €</o>", read_xml(self.out).to_string())

    def test_doctype(self):
        data = self._output_of('<xsl:output doctype-system="x.dtd"/><xsl:template match="/"><o/></xsl:template>')
        self.assertIn(b'SYSTEM "x.dtd"', data)

    def test_method_text(self):
        data = self._output_of('<xsl:output method="text"/><xsl:template match="/">a &lt; b&#10;c</xsl:template>')
        self.assertEqual(data, b"a < b\nc")

    def test_method_html(self):
        data = self._output_of('<xsl:output method="html" html-version="5"/><xsl:template match="/">'
                               '<html><body><br/><script>a &lt; b</script></body></html></xsl:template>')
        self.assertTrue(data.startswith(b"<!DOCTYPE HTML>"), data)
        self.assertIn(b"<br><script>a < b</script>", data)

    def test_cdata_section_elements(self):
        data = self._output_of('<xsl:output cdata-section-elements="o"/><xsl:template match="/"><o>a &lt; b</o></xsl:template>')
        self.assertIn(b"<o><![CDATA[a < b]]></o>", data)

    def test_disable_output_escaping(self):
        data = self._output_of('<xsl:template match="/"><o><xsl:text disable-output-escaping="yes">&lt;raw/&gt;</xsl:text></o></xsl:template>')
        self.assertIn(b"<o><raw/></o>", data)

    def test_character_map(self):
        data = self._output_of('<xsl:output use-character-maps="m"/><xsl:character-map name="m">'
                               '<xsl:output-character character="~" string="TILDE"/></xsl:character-map>'
                               '<xsl:template match="/"><o>~</o></xsl:template>')
        self.assertIn(b"<o>TILDE</o>", data)

    def test_existing_carriage_returns_are_not_doubled(self):
        data = self._output_of('<xsl:output method="text"/><xsl:template match="/">a&#13;&#10;b</xsl:template>')
        self.assertEqual(data, b"a\r\nb")

    def test_creates_missing_folders(self):
        target = os.path.join(self.dir, "new", "sub", "out.xml")
        transform(self.doc, self.list_xsl, output_file=target)
        self.assertTrue(os.path.exists(target))

    def test_path_with_space_and_umlaut(self):
        target = os.path.join(self.dir, "sä ce", "ü t.xml")
        transform(self.doc, self.list_xsl, output_file=target)
        self.assertTrue(os.path.exists(target))

    def test_result_document_resolves_next_to_output(self):
        xsl = self._write("side.xsl", sheet(
            '<xsl:template match="/"><xsl:result-document href="side.xml"><s/></xsl:result-document><main/></xsl:template>'))
        transform(self.doc, xsl, output_file=os.path.join(self.dir, "out", "main.xml"))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "out", "side.xml")))

    def test_dynamic_error_raises(self):
        failing = self._write("fail.xsl", sheet(
            '<xsl:template match="/"><xsl:sequence select="error()"/></xsl:template>'))
        with self.assertRaises(PySaxonApiError):
            transform(self.doc, failing, output_file=self.out)

    def test_unencodable_text_raises(self):
        xsl = self._write("euro.xsl", sheet(
            '<xsl:output method="text" encoding="ISO-8859-1"/><xsl:template match="/">&#8364;</xsl:template>'))
        with self.assertRaises(PySaxonApiError):
            transform(self.doc, xsl, output_file=self.out)


class WriteXmlTest(TestCase):
    def setUp(self):
        super().setUp()
        self.node = read_xml(self._write("simple.xml", "<o><x>ä €</x></o>"))

    def test_defaults(self):
        write_xml(self.node, self.out)
        self.assertEqual(self._read_bytes(self.out), DECLARATION + "<o><x>ä €</x></o>".encode("utf-8"))

    def test_indent_with_lf_line_endings(self):
        write_xml(self.node, self.out, indent=True)
        self.assertEqual(self._read_bytes(self.out),
                         DECLARATION + "\n<o>\n   <x>ä €</x>\n</o>\n".encode("utf-8"))

    def test_indent_false(self):
        write_xml(self.node, self.out, indent=False)
        self.assertNotIn(b"\n", self._read_bytes(self.out))

    def test_encoding(self):
        write_xml(self.node, self.out, encoding="ISO-8859-1")
        self.assertEqual(self._read_bytes(self.out),
                         b'<?xml version="1.0" encoding="ISO-8859-1"?><o><x>\xe4 &#x20ac;</x></o>')
        self.assertIn("<x>ä €</x>", read_xml(self.out).to_string())

    def test_method_text(self):
        write_xml(self.node, self.out, method="text")
        self.assertEqual(self._read_bytes(self.out), "ä €".encode("utf-8"))

    def test_text_result_of_transform(self):
        xsl = self._write("text.xsl", sheet('<xsl:template match="/">a &lt; b</xsl:template>'))
        write_xml(transform(self.doc, xsl), self.out, method="text")
        self.assertEqual(self._read_bytes(self.out), b"a < b")

    def test_omit_xml_declaration_uses_hyphenated_name(self):
        write_xml(self.node, self.out, omit_xml_declaration=True)
        self.assertTrue(self._read_bytes(self.out).startswith(b"<o>"))

    def test_doctype_system(self):
        write_xml(self.node, self.out, doctype_system="x.dtd")
        self.assertIn(b'SYSTEM "x.dtd"', self._read_bytes(self.out))

    def test_cdata_section_elements(self):
        write_xml(self.node, self.out, cdata_section_elements="x")
        self.assertIn(b"<![CDATA[", self._read_bytes(self.out))

    def test_stylesheet_settings_do_not_carry_over(self):
        xsl = self._write("indent.xsl", sheet('<xsl:output indent="yes"/><xsl:template match="/"><o><x/></o></xsl:template>'))
        write_xml(transform(self.doc, xsl), self.out)
        self.assertEqual(self._read_bytes(self.out), DECLARATION + b"<o><x/></o>")

    def test_creates_missing_folders(self):
        target = os.path.join(self.dir, "new", "sub", "out.xml")
        write_xml(self.node, target)
        self.assertTrue(os.path.exists(target))

    def test_roundtrip(self):
        write_xml(self.doc, self.out)
        self.assertEqual(read_xml(self.out).to_string(), self.doc.to_string())

    def test_string_input_is_rejected(self):
        with self.assertRaises(TypeError):
            write_xml("<a/>", self.out)

    def test_unknown_setting_raises(self):
        with self.assertRaises(PySaxonApiError):
            write_xml(self.node, self.out, nonsense="x")
        self.assertFalse(os.path.exists(self.out))

    def test_unencodable_text_raises(self):
        with self.assertRaises(PySaxonApiError):
            write_xml(self.node, self.out, method="text", encoding="ISO-8859-1")


if __name__ == "__main__":
    unittest.main()
