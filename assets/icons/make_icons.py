"""반창고 아이콘 SVG 만들기: python make_icons.py → icon.svg, maskable.svg, badge.svg (PNG는 이 SVG를 크롬으로 렌더링해 static/icons에 넣었다)."""
import sys

def bandage(scale=1.0, body="#FFFFFF", pad="#FFD5DA", dot="#F04452", hole=False):
    # 512 기준, 가운데에서 -45도로 기울인 반창고
    w, h, r = 380 * scale, 150 * scale, 75 * scale
    pw = 124 * scale
    dots = [(-26, -30), (26, -30), (-26, 30), (26, 30), (0, 0)]
    d = "".join(
        f'<circle cx="{x * scale:.1f}" cy="{y * scale:.1f}" r="{11 * scale:.1f}" fill="{dot}"/>' for x, y in dots
    )
    if hole:  # 뱃지: 패드 자리에 구멍(점)만 뚫어 실루엣으로 알아보게
        mask = ('<mask id="m"><rect x="-256" y="-256" width="512" height="512" fill="white"/>'
                + d.replace(f'fill="{dot}"', 'fill="black"')
                + f'<rect x="{-pw/2-6*scale:.1f}" y="{-h/2:.1f}" width="{6*scale:.1f}" height="{h:.1f}" fill="black"/>'
                + f'<rect x="{pw/2:.1f}" y="{-h/2:.1f}" width="{6*scale:.1f}" height="{h:.1f}" fill="black"/></mask>')
        return (f'<g transform="translate(256 256) rotate(-45)">{mask}'
                f'<rect x="{-w/2:.1f}" y="{-h/2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r:.1f}" fill="#fff" mask="url(#m)"/></g>')
    return (f'<g transform="translate(256 256) rotate(-45)">'
            f'<rect x="{-w/2:.1f}" y="{-h/2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r:.1f}" fill="{body}"/>'
            f'<rect x="{-pw/2:.1f}" y="{-h/2 + 14*scale:.1f}" width="{pw:.1f}" height="{h - 28*scale:.1f}" rx="{22*scale:.1f}" fill="{pad}"/>'
            f'{d}</g>')

def svg(inner, bg=None, rounded=True):
    back = ""
    if bg:
        back = f'<rect width="512" height="512" rx="{115 if rounded else 0}" fill="{bg}"/>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">{back}{inner}</svg>'

open("icon.svg", "w").write(svg(bandage(1.0), "#F04452"))
open("maskable.svg", "w").write(svg(bandage(0.78), "#F04452", rounded=False))
open("badge.svg", "w").write(svg(bandage(1.08, hole=True)))
