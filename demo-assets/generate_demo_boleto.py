"""Gera um boleto visual inteiramente sintético para ensaio de palco."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("sabesp-demo.png")
image = Image.new("RGB", (1400, 900), "white")
draw = ImageDraw.Draw(image)


def font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


orange = "#EC7000"
navy = "#172B4D"
draw.rounded_rectangle((55, 50, 1345, 850), radius=24, outline="#B0B7C3", width=3)
draw.rectangle((55, 50, 1345, 165), fill=navy)
draw.text((90, 76), "SABESP", font=font(56, True), fill="white")
draw.text((1040, 88), "2ª VIA", font=font(32, True), fill=orange)

draw.text((90, 205), "DOCUMENTO SINTÉTICO PARA DEMONSTRAÇÃO", font=font(25, True), fill=orange)
draw.text((90, 265), "Beneficiário", font=font(22), fill="#677085")
draw.text((90, 300), "SABESP", font=font(34, True), fill=navy)
draw.text((670, 265), "Vencimento", font=font(22), fill="#677085")
draw.text((670, 300), "03/09/2026", font=font(34, True), fill=navy)
draw.text((1030, 265), "Valor", font=font(22), fill="#677085")
draw.text((1030, 300), "R$ 187,40", font=font(34, True), fill=navy)

draw.line((90, 380, 1310, 380), fill="#D7DBE2", width=2)
draw.text((90, 420), "Linha digitável", font=font(22), fill="#677085")
line = "84670.00000 1 87400.02402 0 60829.05471 1 001001250805"
draw.text((90, 465), line, font=font(31, True), fill="#111827")

# Código de barras visual sintético; não representa um título válido.
x = 110
digits = "1010011100101101001110010110100111001011010010111001011010011100"
for digit in digits * 2:
    width = 5 if digit == "1" else 2
    if digit == "1":
        draw.rectangle((x, 570, x + width, 720), fill="black")
    x += width + 3
    if x > 1280:
        break

draw.text((90, 770), "NÃO PAGÁVEL · DADOS FICTÍCIOS · APF INOVACAMP", font=font(25, True), fill="#B42318")
image.save(OUT, optimize=True)
print(OUT)
