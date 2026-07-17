import re
import streamlit as st
import json
from io import BytesIO
from datetime import datetime, date
import psycopg2

# =============================================================================
# BIBLIOTECAS PARA O PDF (ReportLab)
# =============================================================================
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak

# =============================================================================
# BIBLIOTECAS PARA OS GRÁFICOS (Plotly)
# =============================================================================
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# =============================================================================
# CONSTANTES GLOBAIS (TODAS AS CHAVES MAPEADAS PARA EVITAR KEYERROR)
# =============================================================================
CATEGORIAS_MAP = {
    "infraestrutura": {"label": "Infraestrutura e Setor", "qids": ["1.0", "1.1", "1.2", "1.3", "1.3.1", "1.4", "1.4.1", "1.4.2"]},
    "planejamento":   {"label": "Planejamento (PDTIC)", "qids": ["2.0", "2.1", "2.2", "2.3"]},
    "seguranca":       {"label": "Segurança da Informação", "qids": ["3.0", "3.1", "3.1.1", "3.1.1.1", "3.2", "3.2.1", "3.3", "3.4", "3.5", "3.6", "3.6.1"]},
    "transparencia":   {"label": "Transparência e LAI", "qids": ["4.0", "4.1", "4.2", "6.0", "6.1", "6.2", "6.3", "6.4", "7.0", "7.1", "7.2", "7.3"]},
    "gov_digital":     {"label": "Governo Digital", "qids": ["5.0", "5.1", "5.2", "5.3", "9.0", "9.1", "9.2"]},
    "sistemas":        {"label": "Sistemas de Gestão", "qids": ["8.0", "8.1", "8.2", "8.2.1", "8.2.2", "8.3", "8.4"]},
    "lgpd":            {"label": "LGPD", "qids": ["10.0", "10.1", "10.2", "10.3", "10.4", "10.5", "10.5.1", "11.0", "11.1"]},
}

# Preenchido com 0 nas chaves que faltavam. Ajuste os valores conforme suas regras de negócio.
PONTUACOES_MAX = {
    # Infraestrutura e Setor
    "1.0": 30, "1.1": 30, "1.2": 30, "1.3": 30, "1.3.1": 30, "1.4": 0, "1.4.1": 40, "1.4.2": 20,
    
    # Planejamento (PDTIC)
    "2.0": 40, "2.1": 20, "2.2": 40, "2.3": 20,
    
    # Segurança da Informação
    "3.0": 50, "3.1": 0, "3.1.1": 40, "3.1.1.1": 10, "3.2": 0, "3.2.1": 10, "3.3": 30, "3.4": 30, "3.5": 30, "3.6": 20, "3.6.1": 0,
    
    # Transparência e LAI
    "4.0": 40, "4.1": 0, "4.2": 0, "6.0": 20, "6.1": 20, "6.2": 20, "6.3": 10, "6.4": 30, "7.0": 25, "7.1": 10, "7.2": 10, "7.3": 5,
    
    # Governo Digital
    "5.0": 0, "5.1": 0, "5.2": 0, "5.3": 0, "9.0": 0, "9.1": 120, "9.2": 0,
    
    # Sistemas de Gestão
    "8.0": 40, "8.1": 0, "8.2": 0, "8.2.1": 50, "8.2.2": 30, "8.3": 0, "8.4": 0,
    
    # LGPD
    "10.0": 0, "10.1": 0, "10.2": 0, "10.3": 0, "10.4": 0, "10.5": 0, "10.5.1": 0, "11.0": 0, "11.1": 0
}

FAIXA_CORES = {"C": "#ef4444", "C+": "#f97316", "B": "#eab308", "B+": "#22c55e", "A": "#16a34a"}

# =============================================================================
# MODAL DE AVISO AUTOMÁTICO (CORRIGIDO PARA LINKS CLICÁVEIS)
# =============================================================================
@st.dialog("⚠️ Atenção! Evidência em Link Externo")
def modal_aviso_link(qid, links_encontrados):
    st.warning(f"Detectamos a inclusão de link(s) no campo de evidências da questão **{qid}**.")
    
    for lk in links_encontrados:
        st.markdown(f"🔗 **Endereço:** [{lk}]({lk})")
        
    st.markdown("""
    **Por favor, verifique se este link está configurado para acesso público/compartilhado.**
    
    Se as credenciais estiverem privadas ou exigirem login e senha do seu município, as equipes avaliadoras externas **não conseguirão acessar as provas**, invalidando os pontos desse quesito.
    """)
    if st.button("Confirmo que o link está liberado para o público", key=f"btn_conf_{qid}"):
        st.rerun()

# =============================================================================
# DECORATOR DE SEGURANÇA PARA PEGAR O ERRO OCULTO (ADICIONADO)
# =============================================================================
def diagnosticar_erros(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            st.error("🚨 Um erro aconteceu dentro do formulário!")
            st.code(f"Tipo do erro: {type(e).__name__}\nDetalhes: {str(e)}")
            st.exception(e)
    return wrapper

# ATENÇÃO: Vá até a linha onde diz "def mostrar_formulario_gov():" 
# e adicione "@diagnosticar_erros" logo na linha de cima dela!
