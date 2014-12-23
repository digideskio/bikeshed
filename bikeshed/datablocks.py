# -*- coding: utf-8 -*-
from __future__ import division, unicode_literals
import re
import json
import copy
from collections import OrderedDict, defaultdict

import config
import biblio
from .messages import *

# This function does a single pass through the doc,
# finding all the "data blocks" and processing them.
# A "data block" is any <pre> or <xmp> element.
#
# When a data block is found, the *contents* of the block
# are passed to the appropriate processing function as an
# array of lines.  The function should return a new array
# of lines to replace the *entire* block.
#
# That is, we give you the insides, but replace the whole
# thing.
#
# Additionally, we pass in the tag-name used (pre or xmp)
# and the line with the content, in case it has useful data in it.
def transformDataBlocks(doc):
    inBlock = False
    blockTypes = {
        'propdef': transformPropdef,
        'descdef': transformDescdef,
        'elementdef': transformElementdef,
        'railroad': transformRailroad,
        'biblio': transformBiblio,
        'anchors': transformAnchors,
        'link-defaults': transformLinkDefaults,
        'pre': transformPre
    }
    blockType = ""
    tagName = ""
    startLine = 0
    replacements = []
    for (i, line) in enumerate(doc.lines):
        # Look for the start of a block.
        match = re.match(r"\s*<(pre|xmp)(.*)", line, re.I)
        if match and not inBlock:
            inBlock = True
            startLine = i
            tagName = match.group(1)
            typeMatch = re.search("|".join(blockTypes.keys()), match.group(2))
            if typeMatch:
                blockType = typeMatch.group(0)
            else:
                blockType = "pre"
        # Look for the end of a block.
        match = re.match(r"(.*)</"+tagName+">(.*)", line, re.I)
        if match and inBlock:
            inBlock = False
            if startLine == i:
                # Single-line <pre>.
                match = re.match(r"\s*(<{0}[^>]*>)(.+)</{0}>(.*)".format(tagName), line, re.I)
                doc.lines[i] = match.group(3)
                replacements.append({
                    'start': i,
                    'end': i,
                    'value': blockTypes[blockType](
                        lines=[match.group(2)],
                        tagName=tagName,
                        firstLine=match.group(1),
                        doc=doc)})
            elif re.match(r"^\s*$", match.group(1)):
                # End tag was the first tag on the line.
                # Remove the tag from the line.
                doc.lines[i] = match.group(2)
                replacements.append({
                    'start': startLine,
                    'end': i,
                    'value': blockTypes[blockType](
                        lines=doc.lines[startLine+1:i],
                        tagName=tagName,
                        firstLine=doc.lines[startLine],
                        doc=doc)})
            else:
                # End tag was at the end of line of useful content.
                # Trim this line to be only the block content.
                doc.lines[i] = match.group(1)
                # Put the after-tag content on the next line.
                doc.lines.insert(i+1, match.group(2))
                replacements.append({
                    'start': startLine,
                    'end': i+1,
                    'value': blockTypes[blockType](
                        lines=doc.lines[startLine+1:i+1],
                        tagName=tagName,
                        firstLine=doc.lines[startLine],
                        doc=doc)})
            tagName = ""
            blockType = ""

    # Make the replacements, starting from the bottom up so I
    # don't have to worry about offsets becoming invalid.
    for rep in reversed(replacements):
        doc.lines[rep['start']:rep['end']] = rep['value']


def transformPre(lines, tagName, firstLine, **kwargs):
    # If the last line in the source is a </code></pre>,
    # the generic processor will turn that into a final </code> line,
    # which'll mess up the indent finding.
    # Instead, specially handle this case.
    if len(lines) == 0:
        return [firstLine, "</{0}>".format(tagName)]

    if re.match(r"\s*</code>\s*$", lines[-1]):
        lastLine = "</code></{0}>".format(tagName)
        lines = lines[:-1]
    else:
        lastLine = "</{0}>".format(tagName)

    if len(lines) == 0:
        return [firstLine, lastLine]

    indent = float("inf")
    for (i, line) in enumerate(lines):
        if line.strip() == "":
            continue

        # Use tabs in the source, but spaces in the output,
        # because tabs are ginormous in HTML.
        lines[i] = lines[i].replace("\t", "  ")

        # Find the line with the shortest whitespace prefix.
        # (It might not be the first!)
        indent = min(indent, len(re.match(r" *", lines[i]).group(0)))

    if indent == float("inf"):
        indent = 0

    # Strip off the whitespace prefix from each line
    for (i, line) in enumerate(lines):
        if line.strip() == "":
            continue
        lines[i] = lines[i][indent:]
    # Put the first/last lines back into the results.
    lines[0] = firstLine.rstrip() + lines[0]
    lines.append(lastLine)
    return lines


def transformPropdef(lines, doc, firstLine, **kwargs):
    attrs = OrderedDict()
    parsedAttrs = parseDefBlock(lines, "propdef")
    # Displays entries in the order specified in attrs,
    # then if there are any unknown parsedAttrs values,
    # they're displayed afterward in the order they were specified.
    # attrs with a value of None are required to be present in parsedAttrs;
    # attrs with any other value are optional, and use the specified value if not present in parsedAttrs
    if "partial" in firstLine or "New values" in parsedAttrs:
        attrs["Name"] = None
        attrs["New values"] = None
        ret = ["<table class='definition propdef partial'>"]
    elif "shorthand" in firstLine:
        attrs["Name"] = None
        attrs["Value"] = None
        for defaultKey in ["Initial", "Applies to", "Inherited", "Percentages", "Media", "Computed value", "Animatable"]:
            attrs[defaultKey] = "see individual properties"
        ret = ["<table class='definition propdef'>"]
    else:
        attrs["Name"] = None
        attrs["Value"] = None
        attrs["Initial"] = None
        attrs["Applies to"] = "all elements"
        attrs["Inherited"] = None
        attrs["Percentages"] = "n/a"
        attrs["Media"] = "visual"
        attrs["Computed value"] = "as specified"
        attrs["Animatable"] = "no"
        ret = ["<table class='definition propdef'>"]
    for key, val in attrs.items():
        if key in parsedAttrs or val is not None:
            if key in parsedAttrs:
                val = parsedAttrs[key]
            if key in ("Value", "New values"):
                ret.append("<tr><th>{0}:<td class='prod'>{1}".format(key, val))
            else:
                ret.append("<tr><th>{0}:<td>{1}".format(key, val))
        else:
            die("The propdef for '{0}' is missing a '{1}' line.", parsedAttrs.get("Name", "???"), key)
            continue
    for key, val in parsedAttrs.items():
        if key in attrs:
            continue
        ret.append("<tr><th>{0}:<td>{1}".format(key, val))
    ret.append("</table>")
    return ret

# TODO: Make these functions match transformPropdef's new structure
def transformDescdef(lines, doc, firstLine, **kwargs):
    vals = parseDefBlock(lines, "descdef")
    if "partial" in firstLine or "New values" in vals:
        requiredKeys = ["Name", "For"]
        ret = ["<table class='definition descdef partial' data-dfn-for='{0}'>".format(vals.get("For", ""))]
    if "mq" in firstLine:
        requiredKeys = ["Name", "For", "Value"]
        ret = ["<table class='definition descdef mq' data-dfn-for='{0}'>".format(vals.get("For",""))]
    else:
        requiredKeys = ["Name", "For", "Value", "Initial"]
        ret = ["<table class='definition descdef' data-dfn-for='{0}'>".format(vals.get("For", ""))]
    for key in requiredKeys:
        if key == "For":
            ret.append("<tr><th>{0}:<td><a at-rule>{1}</a>".format(key, vals.get(key,'')))
        elif key == "Value":
            ret.append("<tr><th>{0}:<td class='prod'>{1}".format(key, vals.get(key,'')))
        elif key in vals:
            ret.append("<tr><th>{0}:<td>{1}".format(key, vals.get(key,'')))
        else:
            die("The descdef for '{0}' is missing a '{1}' line.", vals.get("Name", "???"), key)
            continue
    for key in vals.viewkeys() - requiredKeys:
        ret.append("<tr><th>{0}:<td>{1}".format(key, vals[key]))
    ret.append("</table>")
    return ret

def transformElementdef(lines, doc, **kwargs):
    attrs = OrderedDict()
    parsedAttrs = parseDefBlock(lines, "elementdef")
    if "Attribute groups" in parsedAttrs or "Attributes" in parsedAttrs:
        html = "<ul>"
        if "Attribute groups" in parsedAttrs:
            groups = [x.strip() for x in parsedAttrs["Attribute groups"].split(",")]
            for group in groups:
                html += "<li><a dfn data-element-attr-group>{0}</a>".format(group)
            del parsedAttrs["Attribute groups"]
        if "Attributes" in parsedAttrs:
            atts = [x.strip() for x in parsedAttrs["Attributes"].split(",")]
            for att in atts:
                html += "<li><a element-attr for='{1}'>{0}</a>".format(att, parsedAttrs.get("Name", ""))
        html += "</ul>"
        parsedAttrs["Attributes"] = html


    # Displays entries in the order specified in attrs,
    # then if there are any unknown parsedAttrs values,
    # they're displayed afterward in the order they were specified.
    # attrs with a value of None are required to be present in parsedAttrs;
    # attrs with any other value are optional, and use the specified value if not present in parsedAttrs
    attrs["Name"] = None
    attrs["Categories"] = None
    attrs["Contexts"] = None
    attrs["Content model"] = None
    attrs["Attributes"] = None
    attrs["Dom interfaces"] = None
    ret = ["<table class='definition-table elementdef'>"]
    for key, val in attrs.items():
        if key in parsedAttrs or val is not None:
            if key in parsedAttrs:
                val = parsedAttrs[key]
            if key == "Name":
                ret.append("<tr><th>Name:<td>")
                ret.append(', '.join("<dfn element>{0}</dfn>".format(x.strip()) for x in val.split(",")))
            elif key == "Content model":
                ret.append("<tr><th>{0}:<td>".format(key))
                ret.extend(val.split("\n"))
            elif key == "Categories":
                ret.append("<tr><th>Categories:<td>")
                ret.append(', '.join("<a dfn>{0}</a>".format(x.strip()) for x in val.split(",")))
            elif key == "Dom interfaces":
                ret.append("<tr><th>DOM Interfaces:<td>")
                ret.append(', '.join("<a interface>{0}</a>".format(x.strip()) for x in val.split(",")))
            else:
                ret.append("<tr><th>{0}:<td>{1}".format(key, val))
        else:
            die("The elementdef for '{0}' is missing a '{1}' line.", parsedAttrs.get("Name", "???"), key)
            continue
    for key, val in parsedAttrs.items():
        if key in attrs:
            continue
        ret.append("<tr><th>{0}:<td>{1}".format(key, val))
    ret.append("</table>")
    return ret



def parseDefBlock(lines, type):
    vals = OrderedDict()
    lastKey = None
    for line in lines:
        match = re.match(r"\s*([^:]+):\s*(\S.*)", line)
        if match is None:
            if lastKey is not None and (line.strip() == "" or re.match(r"\s+", line)):
                key = lastKey
                val = line.strip()
            else:
                die("Incorrectly formatted {2} line for '{0}':\n{1}", vals.get("Name", "???"), line, type)
                continue
        else:

            key = match.group(1).strip().capitalize()
            lastKey = key
            val = match.group(2).strip()
        if key in vals:
            vals[key] += "\n"+val
        else:
            vals[key] = val
    return vals

def transformRailroad(lines, doc, **kwargs):
    import StringIO
    import railroadparser
    ret = [
        "<div class='railroad'>",
        "<style>svg.railroad-diagram{background-color:hsl(30,20%,95%);}svg.railroad-diagram path{stroke-width:3;stroke:black;fill:rgba(0,0,0,0);}svg.railroad-diagram text{font:bold 14px monospace;text-anchor:middle;}svg.railroad-diagram text.label{text-anchor:start;}svg.railroad-diagram text.comment{font:italic 12px monospace;}svg.railroad-diagram rect{stroke-width:3;stroke:black;fill:hsl(120,100%,90%);}</style>"]
    code = ''.join(lines)
    diagram = railroadparser.parse(code)
    temp = StringIO.StringIO()
    diagram.writeSvg(temp.write)
    ret.append(temp.getvalue())
    temp.close()
    ret.append("</div>")
    return ret

def transformBiblio(lines, doc, **kwargs):
    biblio.processSpecrefBiblioFile(''.join(lines), doc.refs.biblios, order=1)
    return []

def transformAnchors(lines, doc, **kwargs):
    anchors = parseInfoTree(lines, doc.md.indent)
    for anchor in anchors:
        if "type" not in anchor or len(anchor['type']) != 1:
            die("Each anchor needs exactly one type. Got:\n{0}", config.printjson(anchor))
            continue
        if "text" not in anchor or len(anchor['text']) != 1:
            die("Each anchor needs exactly one text. Got:\n{0}", config.printjson(anchor))
            continue
        if "url" not in anchor and "urlPrefix" not in anchor:
            die("Each anchor needs a url and/or at least one urlPrefix. Got:\n{0}", config.printjson(anchor))
            continue
        for key in anchor:
            if key not in ("type", "text", "url", "urlPrefix", "for"):
                die("Unknown key '{0}' in anchor:\n{1}", key, config.printjson(anchor))
                continue
        if "urlPrefix" in anchor:
            urlPrefix = ''.join(anchor['urlPrefix'][0])
        if "url" in anchor:
            urlSuffix = anchor['url'][0]
        else:
            urlSuffix = config.simplifyText(anchor['text'][0])
        url = urlPrefix + ("" if "#" in urlPrefix or "#" in urlSuffix else "#") + urlSuffix
        doc.refs.refs[anchor['text'][0].lower()].append({
            "linkingText": anchor['text'][0],
            "type": anchor['type'][0],
            "url": url,
            "for": anchor.get('for', []),
            "export": True,
            "status": "local"
            })
    return []

def transformLinkDefaults(lines, doc, **kwargs):
    lds = parseInfoTree(lines, doc.md.indent)
    for ld in lds:
        if len(ld.get('type', [])) != 1:
            die("Every link default needs exactly one type. Got:\n{0}", config.printjson(ld))
            continue
        if len(ld.get('spec', [])) != 1:
            die("Every link default needs exactly one spec. Got:\n{0}", config.printjson(ld))
            continue
        if len(ld.get('text', [])) != 1:
            die("Every link default needs exactly one text. Got:\n{0}", config.printjson(ld))
            continue
        doc.md.linkDefaults[ld['text'][0]].append((ld['spec'][0], ld['type'][0], ld.get('status', None), ld.get('for', None)))
    return []


def parseInfoTree(lines, indent=4):
    # Parses sets of info, which can be arranged into trees.
    # Each info is a set of key/value pairs, semicolon-separated:
    # key1: val1; key2: val2; key3: val3
    # Intead of semicolon-separating, pieces can be nested with higher indentation
    # key1: val1
    #     key2: val2
    #         key3: val3
    # Multiple fragments can be chained off of a single higher-level piece,
    # to avoid repetition:
    # key1: val1
    #     key2: val2
    #     key2a: val2a
    # ===
    # key1: val1; key2: val2
    # key1: val1; key2a: val2a

    def extendData(datas, infoLevels):
        newData = defaultdict(list)
        for infos in infoLevels[:lastIndent+1]:
            for k,v in infos.items():
                newData[k].extend(v)
        datas.append(newData)

    # Determine the indents, separate the lines.
    datas = []
    infoLevels = []
    lastIndent = -1
    indentSpace = " " * indent
    for line in lines:
        ws, text = re.match("(\s*)(.*)", line).groups()
        wsLen = len(ws.replace("\t", indentSpace))
        if wsLen % indent != 0:
            die("Line has inconsistent indentation; use tabs or {1} spaces:\n{0}", text, indent)
            return []
        wsLen = wsLen // indent
        if wsLen >= lastIndent+2:
            die("Line jumps {1} indent levels:\n{0}", text, wsLen - lastIndent)
            return []
        if wsLen <= lastIndent:
            # Previous line was a leaf node; build its full data and add to the list
            extendData(datas, infoLevels[:lastIndent+1])
        # Otherwise, chained data. Parse it, put it into infoLevels
        info = defaultdict(list)
        for piece in text.split(";"):
            if piece.strip() == "":
                continue
            match = re.match("([^:]+):\s*(.*)", piece)
            if not match:
                die("Line doesn't match the grammar `k:v; k:v; k:v`:\n{0}", text)
                return []
            key = match.group(1).strip()
            val = match.group(2).strip()
            info[key].append(val)
        if wsLen < len(infoLevels):
            infoLevels[wsLen] = info
        else:
            infoLevels.append(info)
        lastIndent = wsLen
    # Grab the last bit of data.
    extendData(datas, infoLevels[:lastIndent+1])
    return datas
