#!/usr/bin/env python3
# vim: set ts=4 sw=4 noet ai:

import lxml.etree as etree
import subprocess
import re
import tempfile
import math
import io
import os
import sys

class AffineTransform:
	def __init__(s, t=None, m=None):
		s.t = (0.0, 0.0) if t is None else t
		s.m = (1.0,0.0, 0.0,1.0) if m is None else m

	def clone(s):
		nt = AffineTransform()
		nt.t = s.t
		nt.m = s.m
		return nt

	def translate(s, tx, ty):
		s.matrix(1.0,0.0, 0.0,1.0, tx,ty)

	def rotate_degrees(s, angle, cx=0.0, cy=0.0):
		angle = math.radians(angle)
		sin,cos = math.sin(angle), math.cos(angle)
		if cx != 0.0 or cy != 0.0:
			s.translate(cx,cy)
			s.matrix(cos,sin, -sin,cos, 0.0,0.0)
			s.translate(-cx,-cy)
		else:
			s.matrix(cos,sin, -sin,cos, 0.0,0.0)

	def scale(s, sx, sy=None):
		if sy is None:
			sy = sx
		s.matrix(sx,0.0, sy,0.0)

	def matrix(s, a,b,c,d,e=0.0,f=0.0):
		sa,sb,sc,sd = s.m
		se,sf = s.t

		ma = sa*a + sc*b
		mb = sb*a + sd*b
		mc = sa*c + sc*d
		md = sb*c + sd*d
		me = sa*e + sc*f + se
		mf = sb*e + sd*f + sf
		s.m = (ma,mb, mc,md)
		s.t = (me,mf)

	def applyTo(s, x, y=None):
		if y is None:
			x,y = x
		xx = s.t[0] + s.m[0]*x+s.m[2]*y
		yy = s.t[1] + s.m[1]*x+s.m[3]*y
		return (xx,yy)

	def __str__(s):
		return '[{},{},{}  ;  {},{},{}]'.format(s.m[0],s.m[2],s.t[0],s.m[1],s.m[3],s.t[1])

	def __mul__(a, b):
		a11,a21,a12,a22 = a.m
		a13,a23 = a.t
		b11,b21,b12,b22 = b.m
		b13,b23 = b.t

		# cIJ = aI1*b1J + aI2*b2J + aI3*b3J
		c11 = a11*b11 + a12*b21
		c12 = a11*b12 + a12*b22
		c13 = a11*b13 + a12*b23 + a13
		c21 = a21*b11 + a22*b21
		c22 = a21*b12 + a22*b22
		c23 = a21*b13 + a22*b23 + a23
		return AffineTransform((c13,c23), (c11,c21,c12,c22))

PICTURE_PREAMBLE = r"""% Picture generated by svg2latex
\makeatletter
\providecommand\color[2][]{%
  \errmessage{(svg2latex) Color is used for the text in Inkscape, but the package 'color.sty' is not loaded}%
  \renewcommand\color[2][]{}%
}
\providecommand\transparent[1]{%
  \errmessage{(svg2latex) Transparency is used for the text in Inkscape, but the package 'transparent.sty' is not loaded}%
  \renewcommand\transparent[1]{}%
}
\makeatother
\setlength{\unitlength}{1bp}%
"""

ALIGN_LEFT = 0
ALIGN_CENTER = 1
ALIGN_RIGHT = 2

class TeXLabel:
	def __init__(s, pos, texcode):
		s.texcode = texcode
		s.color = (0,0,0)
		s.pos = pos
		s.align = ALIGN_LEFT
		s.fontsize = 10.0
		s.font = None
		s.scale = 1.0

class TeXPicture:
	def __init__(s, width, height):
		s.width = width
		s.height = height
		s.backgroundGraphic = None
		s.labels = []

	def emit_picture(s, stream):
		stream.write('\\begingroup%\n')
		stream.write(PICTURE_PREAMBLE)
		stream.write('\\begin{{picture}}({},{})%\n'.format(s.width, s.height))
		if s.backgroundGraphic is not None:
			stream.write('\\put(0,0){{\\includegraphics{{{}}}}}%\n'.format(s.backgroundGraphic))
		for label in s.labels:
			x,y = label.pos
			r,g,b = label.color
			isBlack = (r == 0) and (g == 0) and (b == 0)
			stream.write('\\put({},{}){{{}}}%\n'.format(x,y, label.texcode))
		stream.write('\\end{picture}%\n')
		stream.write('\\endgroup%\n')

	def add_label(s, label):
		s.labels.append(label)


TEXTEXT_NS = r"http://www.iki.fi/pav/software/textext/"
TEXTEXT_PREFIX = '{' + TEXTEXT_NS + '}'
INKSVG_NAMESPACES = {
   'dc': r"http://purl.org/dc/elements/1.1/",
   'cc': r"http://creativecommons.org/ns#",
   'rdf': r"http://www.w3.org/1999/02/22-rdf-syntax-ns#",
   'svg': r"http://www.w3.org/2000/svg",
   'textext': TEXTEXT_NS,
   'xlink': r"http://www.w3.org/1999/xlink",
   'sodipodi': r"http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
   'inkscape': r"http://www.inkscape.org/namespaces/inkscape",
}

RX_TRANSFORM = re.compile('^\s*(\w+)\(([0-9,\s\.-]*)\)\s*$')

def parse_svg_transform(attribute):
	m = RX_TRANSFORM.match(attribute)
	if m is None:
		raise Exception('bad transform (' + attribute + ')')
	func = m.group(1)
	args = [float(x.strip()) for x in m.group(2).split(',')]
	xform = AffineTransform()
	if func == 'matrix':
		if len(args) != 6:
			raise Exception('bad matrix transform')
		xform.matrix(*args)
	elif func == 'translate':
		if len(args) < 1 or len(args) > 2:
			raise Exception('bad translate transform')
		tx = args[0]
		ty = args[1] if len(args) > 1 else 0.0
		xform.translate(tx,ty)
	elif func == 'scale':
		if len(args) < 1 or len(args) > 2:
			raise Exception('bad scale transform')
		sx = args[0]
		sy = args[1] if len(args) > 1 else sx
		xform.translate(sx,sy)
	else:
		raise Exception('unsupported transform attribute (' + attribute + ')')
	return xform

def split_svg_style(style):
	parts = [x.strip() for x in style.split(';')]
	parts = [x.partition(':') for x in parts if x != '']
	st = {}
	for p in parts:
		st[p[0].strip()] = p[2].strip()
	return st

def compute_svg_transform(el):
	xform = AffineTransform()
	while el is not None:
		if 'transform' in el.attrib:
			t = parse_svg_transform(el.attrib['transform'])
			xform = t * xform
		el = el.getparent()
	return xform

def interpret_svg_text(textEl, texDoc):
	lines = []
	style = split_svg_style(textEl.attrib['style']) if 'style' in textEl.attrib else {}
	for tspan in textEl.xpath('svg:tspan', namespaces=INKSVG_NAMESPACES):
		span_style = style.copy()
		if 'style' in tspan.attrib:
			span_style.update(split_svg_style(tspan.attrib['style']))
		xform = compute_svg_transform(tspan)
		pos = xform.applyTo(float(tspan.attrib['x']), float(tspan.attrib['y']))
		pos = (pos[0], texDoc.height - pos[1])
		# TODO: interpret text style
		texDoc.add_label(TeXLabel(pos, tspan.text))

def process_svg(inpath):
	doc = etree.parse(inpath)
	normalTextElements = doc.xpath('//svg:text', namespaces=INKSVG_NAMESPACES)
	texTextElements = doc.xpath('//*[@textext:text]', namespaces=INKSVG_NAMESPACES)
	# 72 big-points (PostScript points) per inch, 90 SVG "User Units" per inch
	width = float(doc.getroot().attrib['width']) * 72 / 90
	height = float(doc.getroot().attrib['height']) * 72 / 90
	texDoc = TeXPicture(width, height)
	for textEl in normalTextElements:
		interpret_svg_text(textEl, texDoc)
	for textEl in texTextElements:
		print(textEl.attrib[TEXTEXT_PREFIX+'text'])
	return doc, texDoc

def generate_pdf_from_svg(svgData, pdfpath):
	args = ['/usr/bin/inkscape',
				'--without-gui',
				'--export-area-page',
				'--export-ignore-filters',
				'--export-dpi=90',
				'--export-pdf={}'.format(pdfpath)]
	with tempfile.NamedTemporaryFile(suffix='.svg', delete=True) as tmpsvg:
		svgData.write(tmpsvg, encoding='utf-8', xml_declaration=True)
		tmpsvg.flush()
		args.append(tmpsvg.name)
		with subprocess.Popen(args) as proc:
			proc.wait()
			if proc.returncode != 0:
				sys.stderr.write('inkscape svg->pdf failed')

def svgDataToPdfInkscape(xmldata, outpath):
	fl = tempfile.NamedTemporaryFile(suffix='.svg',delete=True)
	fl.write(xmldata)
	fl.flush()
	inkscapeProcess = subprocess.Popen(['/usr/bin/inkscape',
		'--export-area-page','--export-ignore-filters','--export-dpi='+str(PIXELS_PER_INCH),
		'--export-pdf=' + outpath, fl.name],stdin=subprocess.PIPE)
	inkscapeProcess.communicate(xmldata)
	if inkscapeProcess.returncode != 0:
		sys.stderr.write('inkscape returned an error code (' + str(inkscapeProcess.returncode) + ')\n')
	fl.close()

def main():
	xmlData, texDoc = process_svg('test-figure.svg')
	basename, ext = 'test-figure', '.svg'
	texpath = basename + '.tex'
	pdfpath = basename + '.pdf'

	texDoc.backgroundGraphic = pdfpath

	with open(texpath, 'w', encoding='utf-8') as fl:
		texDoc.emit_picture(fl)
	generate_pdf_from_svg(xmlData, pdfpath)

if __name__ == '__main__':
	main()
