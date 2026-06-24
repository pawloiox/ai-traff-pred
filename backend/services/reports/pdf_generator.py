import io
from datetime import datetime
from typing import Any, Dict
from fpdf import FPDF

class DelayReportPDF(FPDF):
    def header(self):
        self.set_font("helvetica", "B", 15)
        self.cell(0, 10, "Port Traffic Pulse - Raport Opoznienia", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.cell(0, 10, f"Strona {self.page_no()}", align="C")

def generate_pdf_bytes(report: Dict[str, Any]) -> bytes:
    """Generuje dokument PDF z danymi raportu (ktory juz zawiera wypelnione pole 'summary' itd.)"""
    pdf = DelayReportPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)

    # Informacje bazowe
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(0, 10, f"Punkt: {report.get('point_name', 'Nieznany')} ({report.get('road', 'Brak drogi')})", new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font("helvetica", size=10)
    dt_str = datetime.fromtimestamp(report.get('ts', datetime.now().timestamp())).strftime("%Y-%m-%d %H:%M:%S")
    pdf.cell(0, 8, f"Data generacji: {dt_str}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Poziom Ryzyka: {str(report.get('level')).upper()}", new_x="LMARGIN", new_y="NEXT")
    
    avg_ratio = round(report.get('avg_ratio', 0) * 100)
    pdf.cell(0, 8, f"Srednia kongestia: {avg_ratio}%", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Naglowek AI/Regulowy
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "Opis Sytuacji (Headline)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=11)
    pdf.multi_cell(0, 6, report.get('headline', 'Brak'))
    pdf.ln(3)

    # Przyczyna
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "Zidentyfikowana Przyczyna", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=11)
    pdf.multi_cell(0, 6, report.get('cause', 'Brak'))
    pdf.ln(3)

    # Rekomendacja
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "Rekomendacja Operacyjna", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=11)
    pdf.multi_cell(0, 6, report.get('recommendation', 'Brak'))

    return bytes(pdf.output())
