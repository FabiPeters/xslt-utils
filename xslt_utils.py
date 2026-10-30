"""Small helpers around the SaxonC Python API for everyday XSLT work.

Typical use::

    from xslt_utils import read_xml, transform, write_xml

    doc = read_xml("input.xml")

    # Write the result as the stylesheet's xsl:output asks.
    transform(doc, "style.xsl", {"lang": "de"}, output_file="output.xml")

    # Multi-step pipeline: intermediate results are nodes.
    step = transform(doc, "step1.xsl")
    transform(step, "step2.xsl", output_file="output.xml")

    # Save a node, choosing the output settings here.
    write_xml(step, "debug.xml", indent=True)

Works with any SaxonC edition (EE, PE or HE); the first one found is used.
"""

import os

try:
    from saxoncee import PySaxonApiError, PySaxonProcessor, PyXdmNode
except ImportError:
    try:
        from saxoncpe import PySaxonApiError, PySaxonProcessor, PyXdmNode
    except ImportError:
        from saxonche import PySaxonApiError, PySaxonProcessor, PyXdmNode

__all__ = ["PySaxonApiError", "get_processor", "read_xml", "transform", "write_xml"]

_IDENTITY_XSL = """<xsl:stylesheet version="3.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:mode on-no-match="shallow-copy"/>
</xsl:stylesheet>
"""

_processor = None


def get_processor():
    """Return the shared PySaxonProcessor, creating it on first use.

    SaxonC is meant to run with a single processor per process, so all
    helpers share this one instead of opening a new one per call.
    """
    global _processor
    if _processor is None:
        _processor = PySaxonProcessor(license=False)
    return _processor


def read_xml(path):
    """Parse the XML file at `path` and return it as a PyXdmNode."""
    return get_processor().parse_xml(xml_file_name=os.path.abspath(path))


def transform(xml, stylesheet, params=None, output_file=None):
    """Transform the PyXdmNode `xml` with the XSLT file `stylesheet`.

    `params` is an optional dict of stylesheet parameter names to values;
    values are passed as xs:string.

    Without `output_file`, the result is returned as a PyXdmNode that keeps
    the location of `xml`, so relative paths in later stylesheets
    (e.g. document(@href)) still resolve. The stylesheet's xsl:output settings
    do not apply, because nothing is serialized yet. A relative
    xsl:result-document href resolves next to the input file.

    With `output_file`, the result is written to that file exactly as the
    stylesheet's xsl:output asks, and None is returned. Missing folders are
    created, and a relative xsl:result-document href resolves next to the
    output file. If the transform fails, PySaxonApiError is raised and
    `output_file` may be left empty or incomplete. On Windows, Saxon may also
    keep it open until the process ends: it can be written again, but not
    renamed or deleted until then.
    """
    _require_node(xml)
    executable = _compile(stylesheet, params)
    if output_file is not None:
        executable.transform_to_file(xdm_node=xml, output_file=os.path.abspath(output_file))
        return None
    options = {"base_output_uri": xml.base_uri} if xml.base_uri else {}
    return executable.transform_to_value(xdm_node=xml, **options).head.get_node_value()


def write_xml(xml, path, **output):
    """Write the PyXdmNode `xml` to the file at `path`. Missing folders are created.

    Keyword arguments are XSLT serialization settings, named like the
    attributes of xsl:output with "_" for "-". True and False become "yes"
    and "no"::

        write_xml(node, "out.xml", indent=True, encoding="ISO-8859-1")
        write_xml(node, "out.txt", method="text")
        write_xml(node, "out.xml", omit_xml_declaration=True, doctype_system="a.dtd")

    The default is XML in UTF-8 with a declaration and no added indentation.
    Settings of the stylesheet that produced the node do not carry over.
    A failed write can leave the file behind as described in transform().
    """
    _require_node(xml)
    executable = get_processor().new_xslt30_processor().compile_stylesheet(
        stylesheet_text=_IDENTITY_XSL
    )
    for name, value in output.items():
        if isinstance(value, bool):
            value = "yes" if value else "no"
        executable.set_property("!" + name.replace("_", "-"), str(value))
    executable.transform_to_file(xdm_node=xml, output_file=os.path.abspath(path))


def _require_node(xml):
    if not isinstance(xml, PyXdmNode):
        raise TypeError(f"expected a PyXdmNode (see read_xml), got {type(xml).__name__}")


def _compile(stylesheet, params):
    """Compile the XSLT file `stylesheet` and set `params` as xs:string parameters."""
    proc = get_processor()
    executable = proc.new_xslt30_processor().compile_stylesheet(
        stylesheet_file=os.path.abspath(stylesheet)
    )
    for name, value in (params or {}).items():
        executable.set_parameter(name, proc.make_string_value(str(value)))
    return executable
