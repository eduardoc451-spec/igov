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

# =============================================================================
# 1. FUNÇÕES DE CONEXÃO E BANCO DE DADOS (POSTGRESQL / NEON)
# =============================================================================

def get_connection():
    """Inicializa e retorna a conexão SQL nativa do Streamlit com o Neon"""
    return st.connection("postgresql", type="sql")

def init_db():
    """Garante que a estrutura da tabela respostas exista no PostgreSQL do Neon"""
    conn = get_connection()
    query_create = """
        CREATE TABLE IF NOT EXISTS respostas (
            id VARCHAR(50) NOT NULL,
            ano INTEGER NOT NULL,
            valor TEXT,
            pontos NUMERIC DEFAULT 0,
            link TEXT,
            comentarios TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id, ano)
        );
    """
    with conn.session as session:
        session.execute(query_create)
        session.commit()

def load_respostas(ano):
    """Busca todas as respostas do Neon filtradas pelo ano selecionado"""
    dados_ano = {}
    conn = get_connection()
    
    # Executa a consulta de forma parametrizada usando a sintaxe do SQLAlchemy (:ano)
    try:
        query = "SELECT id, valor, pontos, link, comentarios FROM respostas WHERE ano = :ano;"
        result = conn.query(query, params={"ano": int(ano)}, ttl="0")
        
        for _, row in result.iterrows():
            comentarios_lista = []
            if row['comentarios']:
                try:
                    comentarios_lista = json.loads(row['comentarios'])
                except Exception:
                    comentarios_lista = []
                    
            dados_ano[str(row['id'])] = {
                "valor": row['valor'], 
                "pontos": float(row['pontos']) if row['pontos'] is not None else 0.0, 
                "link": row['link'],
                "comentarios": comentarios_lista
            }
    except Exception as e:
        st.error(f"Erro ao carregar respostas: {e}")
        
    return dados_ano

def save_resp(qid, valor, pontos, link, comentarios=None):
    """Insere ou Atualiza uma resposta no Neon usando ON CONFLICT (Upsert)"""
    ano_sel = st.session_state.get("ano_referencia_global")
    if not ano_sel:
        return
    
    comentarios_json = "[]"
    if comentarios is not None:
        comentarios_json = json.dumps(comentarios, ensure_ascii=False)
    else:
        dados_atuais = load_respostas(ano_sel)
        if qid in dados_atuais:
            comentarios_json = json.dumps(dados_atuais[qid].get("comentarios", []), ensure_ascii=False)

    conn = get_connection()
    
    # Query compatível com PostgreSQL para fazer UPSERT (Insert ou Update caso já exista a chave)
    query_upsert = """
        INSERT INTO respostas (id, ano, valor, pontos, link, comentarios, atualizado_em)
        VALUES (:id, :ano, :valor, :pontos, :link, :comentarios, CURRENT_TIMESTAMP)
        ON CONFLICT (id, ano) 
        DO UPDATE SET 
            valor = EXCLUDED.valor,
            pontos = EXCLUDED.pontos,
            link = EXCLUDED.link,
            comentarios = EXCLUDED.comentarios,
            atualizado_em = CURRENT_TIMESTAMP;
    """
    
    params = {
        "id": str(qid),
        "ano": int(ano_sel),
        "valor": str(valor),
        "pontos": float(pontos),
        "link": str(link) if link else "",
        "comentarios": comentarios_json
    }
    
    try:
        with conn.session as session:
            session.execute(query_upsert, params)
            session.commit()
    except Exception as e:
        st.error(f"Erro ao salvar {qid} no Neon: {e}")

def bloco_comentarios(questao_id, res_data, sufixo=None):
    """Gera um bloco de diálogo direto com histórico retrátil e controle de status."""
    ano_sel = st.session_state.get("ano_referencia_global", datetime.date.today().year)
    usuario_atual = st.session_state.get("username", st.session_state.get("usuario", "Usuário Anônimo"))
    
    id_chave = f"{questao_id}_{sufixo}" if sufixo else questao_id
    key_texto = f"v_txt_com_{id_chave}_{ano_sel}"
    key_estado_limpar = f"limpar_input_{id_chave}_{ano_sel}"
    
    if key_estado_limpar not in st.session_state:
        st.session_state[key_estado_limpar] = False
        
    st.markdown("---")
    
    dados_questao = res_data.get(questao_id, {})
    historico = dados_questao.get("comentarios", [])
    
    status_global = "Resolvido"
    for com in historico:
        if "status_definido" in com:
            status_global = com["status_definido"]
            
    badge_status = "🔴 PENDENTE" if status_global == "Pendente" else "🟢 RESOLVIDO"
    
    with st.expander(f"💬 Diálogo Interno {id_chave} | Status: {badge_status}", expanded=(status_global == "Pendente")):
        
        st.markdown("<b style='font-size: 13px;'>Status Atual do Quesito:</b>", unsafe_allow_html=True)
        opcoes_status = ["Resolvido", "Pendente"]
        idx_status_atual = opcoes_status.index(status_global)
        
        novo_status_clicado = st.radio(
            f"Definir status para {id_chave}:",
            options=opcoes_status,
            index=idx_status_atual,
            horizontal=True,
            key=f"rad_status_{id_chave}_{ano_sel}",
            label_visibility="collapsed"
        )
        
        if novo_status_clicado != status_global:
            log_mudanca = {
                "autor": "Sistema / " + usuario_atual,
                "data": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                "texto": f"ℹ️ Alterou o status do quesito para: **{novo_status_clicado.upper()}**.",
                "status_definido": novo_status_clicado
            }
            historico.append(log_mudanca)
            save_resp(
                qid=questao_id,
                valor=dados_questao.get("valor", ""),
                pontos=dados_questao.get("pontos", 0),
                link=dados_questao.get("link", ""),
                comentarios=historico
            )
            st.rerun()

        st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

        if historico:
            for idx, com in enumerate(historico):
                col_balao, col_lixeira = st.columns([11, 1])
                
                with col_balao:
                    if "Sistema /" in com['autor']:
                        st.markdown(
                            f"""
                            <div style="background-color: #f1f3f5; padding: 6px 12px; border-radius: 6px; margin-bottom: 4px; border-left: 3px solid #ced4da;">
                                <span style="font-size: 11px; color: #6c757d; font-style: italic;">{com['autor']} - {com['data']}</span>
                                <p style="margin: 2px 0 0 0; font-size: 12px; color: #495057; font-style: italic;">{com['texto']}</p>
                            </div>
                            """, 
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown(
                            f"""
                            <div style="background-color: #f8f9fa; padding: 10px 15px; border-radius: 8px; margin-bottom: 6px; border-left: 3px solid #1e88e5;">
                                <span style="font-size: 11px; color: #1e88e5; font-weight: bold;">{com['autor']}</span> 
                                <span style="font-size: 10px; color: #999; margin-left: 10px;">{com['data']}</span>
                                <p style="margin: 4px 0 0 0; font-size: 13px; color: #333;">{com['texto']}</p>
                            </div>
                            """, 
                            unsafe_allow_html=True
                        )
                
                with col_lixeira:
                    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                    if st.button("🗑️", key=f"btn_del_com_{id_chave}_{idx}_{ano_sel}", help="Excluir este comentário"):
                        historico.pop(idx)
                        save_resp(
                            qid=questao_id,
                            valor=dados_questao.get("valor", ""),
                            pontos=dados_questao.get("pontos", 0),
                            link=dados_questao.get("link", ""),
                            comentarios=historico
                        )
                        st.rerun()
                        
            st.markdown("<br>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='font-size: 12px; color: #999; font-style: italic;'>Nenhum comentário enviado ainda.</p>", unsafe_allow_html=True)
            
        st.markdown("<b style='font-size: 13px;'>Adicionar Novo Comentário:</b>", unsafe_allow_html=True)
        
        if st.session_state[key_estado_limpar]:
            st.session_state[key_texto] = ""
            st.session_state[key_estado_limpar] = False
            
        novo_texto = st.text_area("Digite sua mensagem:", key=key_texto, height=80, label_visibility="collapsed")
        
        col_btn1, _ = st.columns([1, 3])
        with col_btn1:
            if st.button("Postar Comentário", key=f"btn_com_{id_chave}_{ano_sel}", type="primary"):
                if novo_texto.strip():
                    nova_mensagem = {
                        "autor": usuario_atual,
                        "data": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "texto": novo_texto.strip(),
                        "status_definido": status_global
                    }
                    historico.append(nova_mensagem)
                    save_resp(
                        qid=questao_id, 
                        valor=dados_questao.get("valor", ""), 
                        pontos=dados_questao.get("pontos", 0), 
                        link=dados_questao.get("link", ""),
                        comentarios=historico
                    )
                    st.session_state[key_estado_limpar] = True
                    st.rerun()

def get_all_years_data():
    """Busca o histórico completo de todos os anos no Neon"""
    all_data = {}
    conn = get_connection()
    
    try:
        query = "SELECT id, ano, valor, pontos, link, comentarios FROM respostas ORDER BY ano DESC;"
        result = conn.query(query, ttl="0")
        
        for _, row in result.iterrows():
            qid = str(row['id'])
            ano = int(row['ano'])
            valor = row['valor']
            pontos = float(row['pontos']) if row['pontos'] is not None else 0.0
            link = row['link']
            comentarios_raw = row['comentarios']
            
            comentarios_lista = []
            if comentarios_raw:
                try:
                    comentarios_lista = json.loads(comentarios_raw)
                except Exception:
                    comentarios_lista = []
                    
            if ano not in all_data:
                all_data[ano] = {}
            all_data[ano][qid] = {
                "valor": valor, 
                "pontos": pontos, 
                "link": link, 
                "comentarios": comentarios_lista
            }
    except Exception as e:
        st.error(f"Erro ao buscar histórico multiano: {e}")
        
    return all_data

# =============================================================================
# 2. GERADOR DO RELATÓRIO PDF
# =============================================================================
def gerar_relatorio_pdf(dados, ano, total, faixa, all_data=None):
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=30, 
        leftMargin=30, 
        topMargin=30, 
        bottomMargin=50
    )
    elements = []
    styles = getSampleStyleSheet()

    style_titulo_capa = ParagraphStyle('TituloCapa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=24, leading=28, textColor=colors.HexColor("#1b4f72"), alignment=1)

    # -------------------------------------------------------------------------
    # FOLHA 1: CAPA
    # -------------------------------------------------------------------------
    elements.append(Spacer(1, 100))
    
    try:
        # Tenta carregar a imagem local do projeto
        logo = Image("iegm.png", width=380, height=180)
        logo.hAlign = 'CENTER'
        elements.append(logo)
    except Exception:
        # Fallback caso a imagem não exista ou falte no repositório do GitHub
        elements.append(Paragraph("[Logo: iegm.png]", styles["Title"]))
        
    elements.append(Spacer(1, 50))
    elements.append(Paragraph("Relatório I-Gov-TI", style_titulo_capa))
    elements.append(Spacer(1, 15))
    
    style_ano_capa = ParagraphStyle('AnoCapa', parent=styles['Normal'], fontName='Helvetica', fontSize=16, textColor=colors.HexColor("#7f8c8d"), alignment=1)
    elements.append(Paragraph(str(ano), style_ano_capa))
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 2: SUMÁRIO
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>SUMÁRIO</b>", styles["h1"]))
    elements.append(Spacer(1, 30))

    style_item_esquerda = ParagraphStyle('ItemEsq', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor("#2c3e50"))
    style_pag_direita = ParagraphStyle('PagDir', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor("#1b4f72"), alignment=2)

    dados_sumario = [
        [Paragraph("1. Resumo Executivo (Análise Comparativa)", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("2. Análise de Desempenho por Quesito", style_item_esquerda), Paragraph("Pág. 3", style_pag_direita)],
        [Paragraph("3. Análise de Impacto e Penalidades", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("4. Diagnóstico de Reincidências", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("5. Alinhamento com a Agenda 2030 (ODS)", style_item_esquerda), Paragraph("Pág. 4", style_pag_direita)],
        [Paragraph("6. Série Histórica do I-Gov TI", style_item_esquerda), Paragraph("Pág. 5", style_pag_direita)],
    ]
    
    tabela_sumario = Table(dados_sumario, colWidths=[400, 90])
    tabela_sumario.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7"), 1, (2, 4)), 
    ]))
    elements.append(tabela_sumario)
    elements.append(PageBreak())

    # -------------------------------------------------------------------------
    # FOLHA 3+: CONTEÚDO
    # -------------------------------------------------------------------------
    elements.append(Paragraph(f"RELATÓRIO DE AUDITORIA i-GOV TI - {ano}", styles["Title"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>1. RESUMO EXECUTIVO (ANÁLISE COMPARATIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 8))

    # Garantia de conversão correta numérica para evitar NoneType vindo do Neon
    nota_atual = float(total) if total is not None else 0.0
    try:
        ano_atual = int(str(ano).strip()[:4])
    except (ValueError, TypeError):
        ano_atual = datetime.date.today().year
    ano_ant = ano_atual - 1

    def converter_pontos_em_faixa_iegm(pontos):
        pts = float(pontos) if pontos is not None else 0.0
        if pts < 500.0:              return "C"
        elif 500.0 <= pts <= 599.9:  return "C+"
        elif 600.0 <= pts <= 749.9:  return "B"
        elif 750.0 <= pts <= 899.9:  return "B+"
        else:                        return "A"

    if all_data is None:
        all_data = {}

    dados_ano_anterior = all_data.get(ano_ant, {})
    nota_anterior = 0.0
    if ano_ant in all_data:
        # Tratamento preventivo para garantir que campos de pontos nulos do Postgres não quebrem o sum()
        nota_anterior = float(sum(
            float(info_ant.get("pontos", 0) if info_ant.get("pontos") is not None else 0)
            for qid_ant, info_ant in dados_ano_anterior.items() 
            if isinstance(info_ant, dict) and not str(qid_ant).startswith("COM_")
        ))

    faixa_anterior = converter_pontos_em_faixa_iegm(nota_anterior)
    faixa_real_atual = faixa if faixa else converter_pontos_em_faixa_iegm(nota_atual)

    variacao_pontos = nota_atual - nota_anterior
    if nota_anterior > 0:
        variacao_percentual = (variacao_pontos / nota_anterior) * 100
        texto_percentual = f"{variacao_percentual:+.2f}%"
    else:
        texto_percentual = "0.00%"

    if variacao_pontos > 0:
        cor_variacao = colors.HexColor("#28a745")
        seta_tendencia = "▲"
    elif variacao_pontos < 0:
        cor_variacao = colors.HexColor("#dc3545")
        seta_tendencia = "▼"
    else:
        cor_variacao = colors.HexColor("#6c757d")
        seta_tendencia = "■"

    style_th = ParagraphStyle('Th', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.whitesmoke, alignment=1)
    style_td_ano = ParagraphStyle('TdAno', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor("#2c3e50"), alignment=1)
    style_td_pts = ParagraphStyle('TdPts', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, alignment=1)
    style_td_faixa = ParagraphStyle('TdFaixa', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, textColor=colors.HexColor("#1b4f72"), alignment=1)
    style_td_var = ParagraphStyle('TdVar', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, textColor=cor_variacao, alignment=1)

    dados_comparativos = [
        [Paragraph("Exercício", style_th), Paragraph("Pontuação Obtida", style_th), Paragraph("Faixa / Conceito", style_th), Paragraph("Variação Nominal", style_th), Paragraph("Variação Percentual", style_th)],
        [Paragraph(str(ano_ant), style_td_ano), Paragraph(f"{nota_anterior:.1f} pts", style_td_pts), Paragraph(str(faixa_anterior), style_td_faixa), Paragraph("-", style_td_var), Paragraph("-", style_td_var)],
        [Paragraph(str(ano_atual), style_td_ano), Paragraph(f"{nota_atual:.1f} pts", style_td_pts), Paragraph(str(faixa_real_atual), style_td_faixa), Paragraph(f"{seta_tendencia} {variacao_pontos:+.1f} pts", style_td_var), Paragraph(f"{seta_tendencia} {texto_percentual}", style_td_var)]
    ]

    tabela_comp = Table(dados_comparativos, colWidths=[80, 105, 95, 105, 105])
    tabela_comp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")), 
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8f9fa")), ("BACKGROUND", (0, 2), (-1, 2), colors.whitesmoke),          
    ]))
    elements.append(tabela_comp)
    elements.append(Spacer(1, 12))

    style_analise = ParagraphStyle('Analise', parent=styles['Normal'], fontSize=10, leading=14)
    if variacao_pontos > 0:
        texto_analise = f"<b>Análise de Tendência:</b> O município registrou uma evolução de desempenho com incremento de <b>{texto_percentual}</b> na sua pontuação global comparado ao exercício de {ano_ant}."
    elif variacao_pontos < 0:
        texto_analise = f"<b>Análise de Tendência:</b> <font color='#dc3545'><b>Alerta de Retrocesso:</b></font> Foi identificada uma redução de <b>{texto_percentual}</b> na eficiência dos indicadores em relação a {ano_ant}."
    else:
        texto_analise = f"<b>Análise de Tendência:</b> O município apresentou estagnação absoluta (0.00%) no seu índice geral de conformidade."

    elements.append(Paragraph(texto_analise, style_analise))
    elements.append(Spacer(1, 15))

    # 2. ANÁLISE DE DESEMPENHO POR QUESITO
    elements.append(Paragraph("<b>2. ANÁLISE DE DESEMPENHO POR QUESITO</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    lista_pontos_fortes = []
    lista_pontos_fracos = []

    for qid, info in dados.items():
        if str(qid).startswith("COM_") or not isinstance(info, dict): continue
        pts_obtidos = float(info.get("pontos", 0)) if info.get("pontos") is not None else 0.0
        valor_resposta = info.get("valor", "") if info.get("valor") is not None else ""
        link_evidencia = info.get("link", "") if info.get("link") is not None else ""
        pts_maximo = float(PONTUACOES_MAX.get(qid, 0)) if 'PONTUACOES_MAX' in globals() and PONTUACOES_MAX.get(qid) is not None else 10.0
        
        if pts_maximo > 0:
            eficiencia = (pts_obtidos / pts_maximo) * 100
            item_data = {"qid": qid, "pts_obtidos": pts_obtidos, "pts_maximo": pts_maximo, "eficiencia": eficiencia, "valor": valor_resposta, "link": link_evidencia}
            if eficiencia >= 100.0: 
                lista_pontos_fortes.append(item_data)
            elif eficiencia < 100.0:
                lista_pontos_fracos.append(item_data)

    if lista_pontos_fortes:
        elements.append(Paragraph("<b>✅ Pontos Fortes:</b>", styles["h3"]))
        data_fortes = [["Quesito", "Nota / Teto", "Eficiência", "Resposta / Evidência"]]
        for item in sorted(lista_pontos_fortes, key=lambda x: x["pts_obtidos"], reverse=True):
            evidencia = f"<b>{item['valor']}</b><br/>{item['link']}"
            data_fortes.append([item['qid'], f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", f"{item['eficiencia']:.1f}%", Paragraph(evidencia, styles["Normal"])])
        tabela_fortes = Table(data_fortes, colWidths=[65, 75, 65, 285])
        tabela_fortes.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#28a745")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (2, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#28a745")), ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(tabela_fortes)
        elements.append(Spacer(1, 12))

    if lista_pontos_fracos:
        elements.append(Paragraph("<b>⚠️ Pontos Fracos Geral:</b>", styles["h3"]))
        data_fracos = [["Quesito", "Nota / Teto", "Eficiência", "Resposta / Evidência"]]
        for item in sorted(lista_pontos_fracos, key=lambda x: x["pts_obtidos"]):
            evidencia = f"<b>{item['valor']}</b><br/>{item['link']}"
            data_fracos.append([item['qid'], f"{item['pts_obtidos']:.1f} / {item['pts_maximo']:.1f}", f"{item['eficiencia']:.1f}%", Paragraph(evidencia, styles["Normal"])])
        tabela_fracos = Table(data_fracos, colWidths=[65, 75, 65, 285])
        tabela_fracos.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e67e22")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("ALIGN", (0, 0), (2, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e67e22")), ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(tabela_fracos)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>3. ANÁLISE DE IMPACTO E PENALIDADES (EFICIÊNCIA PREVENTIVA)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    PENALIDADES_MAX = {
        "8.3": -51.0,
        "8.4": -51.0
    }

    lista_penalidades = []
    
    for qid, pen_max in PENALIDADES_MAX.items():
        info = dados.get(qid, {}) if isinstance(dados.get(qid), dict) else {"pontos": 0.0, "valor": "Não Respondido", "link": ""}
        
        try:
            nota_real = float(info.get("pontos", 0.0)) if info.get("pontos") is not None else 0.0
        except (ValueError, TypeError):
            nota_real = 0.0
        
        if nota_real < 0:
            eficiencia_preventiva = 0.0
            status_html = "<font color='#dc3545'><b>Impacto Máximo Aplicado</b></font>"
        else:
            eficiencia_preventiva = 100.0
            status_html = "<font color='#28a745'><b>Risco Mitigado (Sem Penalidade)</b></font>"

        lista_penalidades.append({
            "qid": qid,
            "nota_real": nota_real,
            "pen_max": pen_max,
            "eficiencia": eficiencia_preventiva,
            "status": status_html
        })

    data_penalidades = [["Quesito", "Nota Obtida", "Penalidade Máxima", "Eficiência Preventiva", "Status de Risco"]]
    
    for item in sorted(lista_penalidades, key=lambda x: x["eficiencia"]):
        nota_txt = f"{item['nota_real']:.1f} pts"
        teto_txt = f"{item['pen_max']:.1f} pts"
        ef_txt = f"{item['eficiencia']:.1f}%"
        
        data_penalidades.append([
            item['qid'], 
            nota_txt, 
            teto_txt, 
            ef_txt, 
            Paragraph(item['status'], styles["Normal"]) 
        ])
        
    tabela_pen = Table(data_penalidades, colWidths=[65, 100, 110, 115, 150])
    tabela_pen.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4f72")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#1b4f72")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(tabela_pen)
    elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 4. DIAGNÓSTICO DE REINCIDÊNCIAS 
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>4. DIAGNÓSTICO DE REINCIDÊNCIAS </b>", styles["h2"]))
    elements.append(Spacer(1, 6))
    
    reincidencias_detectadas = []
    
    # Dicionário de tetos oficiais para validar apenas quesitos de nota real
    TETOS_VALIDOS = {
        "1.0": 30, "1.1": 30, "1.2": 30, "1.3": 30, "1.3.1": 30, "1.4.1": 40, "1.4.2": 20,
        "2.0": 40, "2.1": 20, "2.2": 40, "2.3": 20,
        "3.0": 50, "3.1": 20, "3.1.1": 40, "3.1.1.1": 10, "3.2.1": 10, "3.3": 30, "3.4": 30, "3.5": 30, "3.6": 20,
        "4.0": 40, "6.0": 20, "6.1": 20, "6.2": 20, "6.3": 10, "6.4": 30, "7.0": 25, "7.1": 10, "7.2": 10, "7.3": 5,
        "8.0": 40, "8.2.1": 50, "8.2.2": 30, "9.1": 120, 
    }
    
    for qid, info_atual in dados.items():
        # Ignora comentários e chaves inválidas
        if str(qid).startswith("COM_") or not isinstance(info_atual, dict): 
            continue
            
        # CRÍTICO: Só avalia se o quesito pertencer à lista de pontuações oficiais
        if qid not in TETOS_VALIDOS:
            continue
            
        pts_maximo = float(TETOS_VALIDOS[qid])
        pts_obtidos_atual = float(info_atual.get("pontos", 0.0)) if info_atual.get("pontos") is not None else 0.0
        
        # Só analisa se o teto for válido e se houve falha real no ano atual (eficiência < 50%)
        if pts_maximo > 0 and (pts_obtidos_atual / pts_maximo) * 100 < 50.0:
            # Busca o mesmo quesito no ano anterior
            info_ant = dados_ano_anterior.get(qid, {}) if isinstance(dados_ano_anterior, dict) else {}
            pts_obtidos_ant = float(info_ant.get("pontos", 0.0)) if isinstance(info_ant, dict) and info_ant.get("pontos") is not None else 0.0
            
            # Se também falhou no ano anterior (eficiência < 50%), temos uma Reincidência Crônica
            if (pts_obtidos_ant / pts_maximo) * 100 < 50.0:
                # Define a categoria dinamicamente com base no prefixo do quesito
                if str(qid).startswith("1") or str(qid).startswith("2") or str(qid).startswith("5"):
                    origem = "Governança de TI"
                elif str(qid).startswith("6") or str(qid).startswith("7"):
                    origem = "Transparência Digital"
                else:
                    origem = "Segurança / Operação"
                    
                reincidencias_detectadas.append({
                    "qid": qid,
                    "tipo": origem,
                    "detalhe": "Ineficiência Crônica de Desempenho (Abaixo de 50% por 2 anos)",
                    "ant": f"{pts_obtidos_ant:.1f} pts",
                    "atual": f"{pts_obtidos_atual:.1f} pts"
                })

    if reincidencias_detectadas:
        data_reinc = [["Quesito", "Origem da Falha", "Impacto Histórico", "Exercício Anterior", "Exercício Atual"]]
        # Ordena a tabela pelo ID do quesito de forma segura
        for reinc in sorted(reincidencias_detectadas, key=lambda x: [float(i) for i in str(x["qid"]).split('.') if i.isdigit()]): 
            data_reinc.append([
                reinc["qid"], 
                reinc["tipo"], 
                Paragraph(f"<b>{reinc['detalhe']}</b>", styles["Normal"]), 
                reinc["ant"], 
                reinc["atual"]
            ])
            
        tabela_reinc = Table(data_reinc, colWidths=[65, 115, 170, 75, 65])
        tabela_reinc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c0392b")), 
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), 
            ("ALIGN", (0, 0), (-1, 0), "CENTER"), 
            ("ALIGN", (0, 1), (1, -1), "CENTER"), 
            ("ALIGN", (3, 1), (-1, -1), "CENTER"), 
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c0392b")), 
            ("FONTSIZE", (0, 0), (-1, -1), 9), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(tabela_reinc)
    else: 
        elements.append(Paragraph("<font color='#28a745'><b>✅ Nenhuma reincidência ativa detectada. O município corrigiu ou mitigou as falhas do ano anterior.</b></font>", styles["Normal"]))
        
    elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)
    # -------------------------------------------------------------------------
    import reportlab.lib.colors as rl_colors

    elements.append(Paragraph("<b>5. ALINHAMENTO COM A AGENDA 2030 (METAS ODS / ONU)</b>", styles["h2"]))
    elements.append(Spacer(1, 6))

    def calcular_percentual_checklist(resposta_bruta, total_itens):
        if not resposta_bruta: 
            return 0.0
        
        if str(resposta_bruta).startswith("["):
            try:
                import ast
                itens_lista = ast.literal_eval(str(resposta_bruta))
                if isinstance(itens_lista, list):
                    itens_validos = [str(i).strip().lower() for i in itens_lista if "outros" not in str(i).lower()]
                    return min((len(itens_validos) / total_itens) * 100.0, 100.0) if total_itens > 0 else 0.0
            except Exception:
                pass
                
        itens = [i.strip().lower() for i in str(resposta_bruta).split(",") if i.strip()]
        itens_validos = [i for i in itens if "outros" not in i]
        return min((len(itens_validos) / total_itens) * 100.0, 100.0) if total_itens > 0 else 0.0

    REGRAS_ODS = {
        "1.0": {"metas": "16.6, 17.8", "total_chk": 0}, "1.2": {"metas": "9.c", "total_chk": 0},
        "1.3": {"metas": "9.c, 16.6, 17.8", "total_chk": 0}, "1.4": {"metas": "16.6, 17.8", "total_chk": 0},
        "1.4.2": {"metas": "16.6, 17.8", "total_chk": 0}, "2.0": {"metas": "16.6, 16.7, 17.8", "total_chk": 0},
        "3.0": {"metas": "16.6, 16.a, 17.8", "total_chk": 0}, "3.1": {"metas": "16.6", "total_chk": 0},
        "3.1.1": {"metas": "16.6", "total_chk": 0}, "3.3": {"metas": "16.6, 16.7, 17.8", "total_chk": 0},
        "3.4": {"metas": "9.c, 16.6", "total_chk": 0}, "3.5": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "3.6": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0}, "4.0": {"metas": "16.5, 16.6, 17.8", "total_chk": 0},
        "5.0": {"metas": "9.4, 16.5, 16.6, 17.14", "total_chk": 0}, "6.0": {"metas": "16.6, 17.8", "total_chk": 0},
        "6.1": {"metas": "9.c, 16.7, 17.8", "total_chk": 0}, "6.2": {"metas": "16.6", "total_chk": 0},
        "6.3": {"metas": "16.6, 16.7", "total_chk": 0}, "6.4": {"metas": "10.2, 16.6, 17.8", "total_chk": 0},
        "7.0": {"metas": "16.5, 16.6, 17.8", "total_chk": 0}, "7.1": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "7.2": {"metas": "16.5, 16.6, 17.8", "total_chk": 0}, "7.3": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "8.0": {"metas": "16.5, 16.6, 17.8, 17.14", "total_chk": 0}, "8.1": {"metas": "16.5, 16.6, 17.8", "total_chk": 17},
        "8.2": {"metas": "16.5, 16.6, 17.8", "total_chk": 17}, "8.2.1": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "8.4": {"metas": "16.5, 16.6, 17.8", "total_chk": 17}, "9.0": {"metas": "10.2, 16.6, 17.8", "total_chk": 0},
        "9.1": {"metas": "16.6", "total_chk": 16}, "10.0": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "10.3": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0}, "10.4": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0},
        "10.5": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0}, "11.0": {"metas": "16.5, 16.6, 16.7, 17.8", "total_chk": 0}
    }

    analise_ods = []
    dados_reference = dados if 'dados' in locals() else {}

    for qid, config in REGRAS_ODS.items():
        info = dados_reference.get(qid, {}) if isinstance(dados_reference, dict) else {"valor": "Não Respondido"}
        if not isinstance(info, dict):
            info = {"valor": str(info)}
            
        resp = str(info.get("valor", "")).strip()
        resp_l = resp.lower()
        
        if not resp or resp_l == "não respondido" or resp == "[]": 
            continue
            
        if config["total_chk"] > 0:
            pct = calcular_percentual_checklist(resp, config["total_chk"])
            status = f"{pct:.1f}% Atendido"
        else:
            if qid == "6.2":
                status = "Atendido" if "possibilita para todos os relatórios" in resp_l else "Não Atendido"
            elif qid == "7.3":
                status = "Atendido" if "não" in resp_l else "Não Atendido"
            elif qid == "8.2.1":
                status = "Atendido" if "totalmente integrado" in resp_l else "Não Atendido"
            elif qid == "10.3":
                status = "Atendido" if "todos os contratos vigentes" in resp_l else "Não Atendido"
            elif "não" in resp_l and qid in ["5.1.2"]: 
                status = "Atendido"
            elif "sim" in resp_l or "parcialmente" in resp_l or "integralmente" in resp_l or "todas" in resp_l or "maior parte" in resp_l:
                status = "Atendido"
            else:
                status = "Não Atendido"

        exibicao_resp = resp.replace("[", "").replace("]", "").replace("'", "") if resp.startswith("[") else resp

        analise_ods.append({
            "qid": qid,
            "status": status,
            "metas": config["metas"],
            "resp": exibicao_resp[:45] + "..." if len(exibicao_resp) > 45 else exibicao_resp
        })

    if analise_ods:
        data_ods = [["Quesito", "Resposta Informada", "Vínculo Metas ODS", "Status de Cumprimento"]]
        style_td_ods = ParagraphStyle('TdOds', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=1)
        
        for item in sorted(analise_ods, key=lambda x: [float(i) if i.replace('.','',1).isdigit() else 999 for i in str(x['qid']).split('.')]):
            st_txt = item["status"]
            if "Não Atendido" in st_txt:
                st_p = Paragraph(f"<font color='#dc3545'><b>{st_txt}</b></font>", style_td_ods)
            elif "Atendido" in st_txt and "%" not in st_txt:
                st_p = Paragraph(f"<font color='#28a745'><b>{st_txt}</b></font>", style_td_ods)
            else:
                st_p = Paragraph(f"<font color='#007bff'><b>{st_txt}</b></font>", style_td_ods)
                
            data_ods.append([
                item["qid"], 
                Paragraph(item["resp"], styles["Normal"]), 
                item["metas"], 
                st_p
            ])
            
        tabela_ods = Table(data_ods, colWidths=[60, 200, 115, 110])
        tabela_ods.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#0f9d58")), 
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.whitesmoke), 
            ("ALIGN", (0, 0), (0, -1), "CENTER"), 
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#0f9d58")), 
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(tabela_ods)
        elements.append(Spacer(1, 15))

    # -------------------------------------------------------------------------
    # 6. SÉRIE HISTÓRICA DO I-GOV TI (CONSOLIDADO FINAL)
    # -------------------------------------------------------------------------
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    import reportlab.lib.colors as rl_colors
    import streamlit as st

    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>6. SÉRIE HISTÓRICA DO I-GOV TI (CONSOLIDADO FINAL)</b>", styles["h2"]))
    elements.append(Spacer(1, 10))

    anos_serie = [2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030]
    valores_serie = []
    
    ano_reference = int(ano) if 'ano' in locals() and ano is not None else 2026
    nota_reference = float(total) if 'total' in locals() and total is not None else 0.0

    for a in anos_serie:
        if a == ano_reference: 
            if nota_reference > 0.0:
                valores_serie.append(min(nota_reference, 1000.0))
            elif dados_reference and isinstance(dados_reference, dict):
                nota_recuperada = float(sum(float(info_h.get("pontos", 0.0) if info_h.get("pontos") is not None else 0.0) for qid_h, info_h in dados_reference.items() if isinstance(info_h, dict) and not str(qid_h).startswith("COM_")))
                valores_serie.append(min(nota_recuperada, 1000.0))
            else:
                valores_serie.append(0.0)
                
        elif all_data and a in all_data:
            dados_ano = all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(sum(float(info_h.get("pontos", 0.0) if info_h.get("pontos") is not None else 0.0) for qid_h, info_h in dados_ano.items() if isinstance(info_h, dict) and not str(qid_h).startswith("COM_")))
                valores_serie.append(min(pontos_ano, 1000.0))
            else:
                valores_serie.append(min(float(dados_ano), 1000.0))

        elif hasattr(st, 'session_state') and 'all_data' in st.session_state and a in st.session_state.all_data:
            dados_ano = st.session_state.all_data[a]
            if isinstance(dados_ano, dict):
                pontos_ano = float(sum(float(info_h.get("pontos", 0.0) if info_h.get("pontos") is not None else 0.0) for qid_h, info_h in dados_ano.items() if isinstance(info_h, dict) and not str(qid_h).startswith("COM_")))
                valores_serie.append(min(pontos_ano, 1000.0))
            else:
                valores_serie.append(min(float(dados_ano), 1000.0))
                
        else: 
            valores_serie.append(0.0)

    desenho_grafico = Drawing(480, 165)
    bc = VerticalBarChart()
    bc.x = 45
    bc.y = 25
    bc.height = 110
    bc.width = 410
    bc.data = [valores_serie]
    bc.categoryAxis.categoryNames = [str(a) for a in anos_serie]
    bc.categoryAxis.labels.fontSize = 9
    bc.categoryAxis.labels.fontName = 'Helvetica-Bold'
    bc.categoryAxis.labels.dy = -10
    
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = 1000
    bc.valueAxis.valueStep = 200
    bc.valueAxis.labels.fontSize = 8
    
    bc.barLabels.nudge = 8
    bc.barLabels.fontSize = 8
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabelFormat = '%.1f'
    
    bc.bars[0].fillColor = rl_colors.HexColor("#1b4f72")
    bc.bars[0].strokeColor = rl_colors.HexColor("#2c3e50")
    bc.bars[0].strokeWidth = 0.5

    desenho_grafico.add(String(240, 150, "Série Histórica do I-Gov TI", textAnchor='middle', fontName='Helvetica-Bold', fontSize=12, fillColor=rl_colors.HexColor("#2c3e50")))
    desenho_grafico.add(bc)
    
    elements.append(desenho_grafico)
    elements.append(Spacer(1, 15))
def mostrar_formulario_gov():
    # =========================================================================
    # CORREÇÃO CRÍTICA PARA CONFLITO DE ESCOPO DO 're' (UNBOUNDLOCALERROR)
    # =========================================================================
    global re
    import sys
    re = sys.modules['re']
    # =========================================================================

    init_db()
    total_pts, res_data, ano_sel = render_sidebar()
    
    st.markdown("""
        <style>
        .quesito-card {
            background-color: #f8f9fa;
            padding: 20px;
            border-left: 6px solid #1e3a5f;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #ddd;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title(f"📊 Auditoria i-Gov TI - {ano_sel}")
    
    aba_quest, aba_graf = st.tabs(["📋 Questionário", "📈 Gráficos"])
    
    with aba_quest:
        st.write("Conteúdo do questionário aqui...")

        # --- SEÇÃO 1: INFRAESTRUTURA E SETOR ---
        st.header("1.0 Estrutura de TIC")
        
        st.markdown("""
            <div class='quesito-card'>
                <h4>Quesito 1.0 - Estrutura Organizacional e Setor de TIC</h4>
                <p>Verifique se o município possui setor formal de TIC instituído na estrutura administrativa, com atribuições e cargos definidos.</p>
            </div>
        """, unsafe_allow_html=True)
        
        info_q1 = res_data.get("1.0", {})
        valor_salvo_q1 = info_q1.get("valor", "Não Respondido")
        pontos_salvos_q1 = float(info_q1.get("pontos", 0.0))
        coment_salvo_q1 = res_data.get("COM_1.0", {}).get("valor", "")
        
        opcoes_q1 = ["Não Respondido", "Não Possui", "Possui Setor (Sem cargos formais)", "Possui Estrutura Formalizada"]
        idx_q1 = opcoes_q1.index(valor_salvo_q1) if valor_salvo_q1 in opcoes_q1 else 0
        
        resp_q1 = st.selectbox("Situação encontrada:", opcoes_q1, index=idx_q1, key="resp_1_0")
        pts_q1 = st.number_input("Pontuação atribuída (Teto: 30 pts):", min_value=0.0, max_value=30.0, value=pontos_salvos_q1, step=5.0, key="pts_1_0")
        coment_q1 = str(st.text_area("Observações / Evidências da Auditoria:", value=coment_salvo_q1, key="com_1_0")).strip()
        
        if resp_q1 != valor_salvo_q1 or pts_q1 != pontos_salvos_q1 or coment_q1 != coment_salvo_q1:
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO respostas (ano, quesito, valor, pontos) VALUES (?, ?, ?, ?) ON CONFLICT(ano, quesito) DO UPDATE SET valor=excluded.valor, pontos=excluded.pontos",
                    (ano_sel, "1.0", resp_q1, pts_q1)
                )
                conn.execute(
                    "INSERT INTO respostas (ano, quesito, valor, pontos) VALUES (?, ?, ?, ?) ON CONFLICT(ano, quesito) DO UPDATE SET valor=excluded.valor, pontos=excluded.pontos",
                    (ano_sel, "COM_1.0", coment_q1, 0.0)
                )
                conn.commit()
            st.rerun()

    with aba_graf:
        st.subheader("📊 Resumo Analítico do Exercício")
        st.write(f"Análise de desempenho consolidada para o ano de {ano_sel}:")
        
        progresso = min(total_pts / 1000.0, 1.0)
        st.progress(progresso)
        st.info(f"O município atingiu **{total_pts:.1f}** de um teto máximo de **1000.0** pontos possíveis no modelo i-Gov TI.")

    return total_pts, res_data, ano_sel
       
        # =============================================================================
        # QUESITO 1.0 • SETOR DE TIC (100% INDEPENDENTE COM 8 ESPAÇOS DE INDENTAÇÃO)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_0_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.0 - Setor de Tecnologia da Informação e Comunicação", expanded=True):
                st.subheader("1.0 • Setor de TIC")
                st.write("**A Prefeitura possui uma área ou setor que cuida de Tecnologia da Informação e Comunicação (TIC)?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes10 = ["Selecione...", "Sim – 30", "Não – 00"]
                
                # Recupera o estado salvo no dicionário de dados históricos
                d10 = res_data.get("1.0", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d10 is None: d10 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_10 = d10.get("valor", "Selecione...")
                chave_radio_10 = f"r_10_{v_salvo_10}_{ano_sel}"

                def cb_radio_10():
                    val = st.session_state[chave_radio_10]
                    pts = 30.0 if "Sim" in val else 0.0
                    lnk = st.session_state.get(f"l_10_txt_{ano_sel}", d10.get("link", ""))
                    
                    save_resp("1.0", val, pts, lnk)
                    res_data["1.0"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_10():
                    lnk = st.session_state[f"l_10_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_10, v_salvo_10)
                    pts = 30.0 if "Sim" in val else 0.0
                    
                    save_resp("1.0", val, pts, lnk)
                    res_data["1.0"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d10.get("link", "") or "")]
                    
                    if lnk != d10.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_0_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx10 = opcoes10.index(v_salvo_10) if v_salvo_10 in opcoes10 else 0
                    st.radio(
                        "Selecione 1.0:", 
                        options=opcoes10, 
                        index=idx10, 
                        key=chave_radio_10,
                        on_change=cb_radio_10,
                        label_visibility="collapsed"
                    )
                    
                with col2:
                    link_10 = st.text_area(
                        "Link/Evidência (1.0):", 
                        value=d10.get("link", ""), 
                        key=f"l_10_txt_{ano_sel}", 
                        on_change=cb_text_10, 
                        placeholder="Insira o link da lei de estrutura administrativa, organograma oficial ou portaria de nomeação da equipe de TIC...",
                        height=100
                    )
                    placeholder_links_10 = st.empty()
                    links_10_visuais = [u[0] for u in re.findall(regex_pure_url, link_10 or "")]
                    if links_10_visuais:
                        placeholder_links_10.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_10_visuais]))

                pts_atuais_10 = d10.get("pontos", 0.0)
                cor_txt_10 = "#28a745" if pts_atuais_10 == 30.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_10}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.0: +{pts_atuais_10:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.0", res_data, ano_sel)

        # GATILHO DO MODAL 1.0
        if st.session_state.get(f"gatilho_modal_1_0_{ano_sel}", False):
            modal_aviso_link("1.0", st.session_state.get(f"links_pendentes_1_0_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_0_{ano_sel}"] = False

        # =============================================================================
        # QUESITO 1.1 • QUANTIDADE DA EQUIPE DE TIC (100% INDEPENDENTE VIA CALLBACKS)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_1_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.1 - Composição de Recursos Humanos do Setor de TIC", expanded=True):
                st.subheader("1.1 • Recursos Humanos em TIC")
                st.write("**Informe a quantidade da equipe que atua no suporte e atendimento de primeiro nível:**")
                st.caption("ℹ *Regra: (Concursados + Comissionados + Estagiários) > 0 garante +30 pontos. Salvamento via eventos nativos.*")

                # Recupera e trata o estado inicial do dicionário com segurança
                d11 = res_data.get("1.1", {"valor": "0", "pontos": 0.0, "link": ""})
                if d11 is None: d11 = {"valor": "0", "pontos": 0.0, "link": ""}

                v_conc_i, v_comi_i, v_esta_i, v_outr_i = 0, 0, 0, 0
                evidencia_11_salva = ""
                raw_link = d11.get("link", "")

                if raw_link:
                    try:
                        if "|LINK:" in raw_link:
                            contadores_part, evidencia_11_salva = raw_link.split("|LINK:", 1)
                        else:
                            contadores_part = raw_link
                        
                        parts = contadores_part.split(",")
                        v_conc_i = int(parts[0].split(":")[1])
                        v_comi_i = int(parts[1].split(":")[1])
                        v_esta_i = int(parts[2].split(":")[1])
                        v_outr_i = int(parts[3].split(":")[1])
                    except Exception:
                        v_conc_i, v_comi_i, v_esta_i, v_outr_i = 0, 0, 0, 0

                # Definição unificada dos Callbacks do Quesito 1.1 para inputs numéricos e área de texto
                def cb_processa_e_salva_11():
                    c_val = int(st.session_state.get(f"q11_num_conc_{ano_sel}", v_conc_i))
                    co_val = int(st.session_state.get(f"q11_num_comi_{ano_sel}", v_comi_i))
                    e_val = int(st.session_state.get(f"q11_num_esta_{ano_sel}", v_esta_i))
                    o_val = int(st.session_state.get(f"q11_num_outr_{ano_sel}", v_outr_i))
                    lnk_val = st.session_state.get(f"l_11_txt_area_{ano_sel}", evidencia_11_salva)

                    total_p = c_val + co_val + e_val
                    pts_calculados = 30.0 if total_p > 0 else 0.0
                    composite_string = f"C:{c_val},Co:{co_val},E:{e_val},O:{o_val}|LINK:{lnk_val.strip()}"

                    save_resp("1.1", str(total_p), pts_calculados, composite_string)
                    res_data["1.1"] = {"valor": str(total_p), "pontos": pts_calculados, "link": composite_string}

                    # Avaliação do gatilho do modal baseado na alteração da URL limpa
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk_val or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, evidencia_11_salva or "")]
                    
                    if lnk_val != evidencia_11_salva and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_1_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = True

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.markdown('<label style="font-size: 14px; font-weight: 500;">Concursados:</label>', unsafe_allow_html=True)
                    st.number_input("", min_value=0, step=1, value=v_conc_i, key=f"q11_num_conc_{ano_sel}", on_change=cb_processa_e_salva_11, label_visibility="collapsed")
                with col2:
                    st.markdown('<label style="font-size: 14px; font-weight: 500;">Comissionados:</label>', unsafe_allow_html=True)
                    st.number_input("", min_value=0, step=1, value=v_comi_i, key=f"q11_num_comi_{ano_sel}", on_change=cb_processa_e_salva_11, label_visibility="collapsed")
                with col3:
                    st.markdown('<label style="font-size: 14px; font-weight: 500;">Estagiários:</label>', unsafe_allow_html=True)
                    st.number_input("", min_value=0, step=1, value=v_esta_i, key=f"q11_num_esta_{ano_sel}", on_change=cb_processa_e_salva_11, label_visibility="collapsed")
                with col4:
                    st.markdown('<label style="font-size: 14px; font-weight: 500;">Outros:</label>', unsafe_allow_html=True)
                    st.number_input("", min_value=0, step=1, value=v_outr_i, key=f"q11_num_outr_{ano_sel}", on_change=cb_processa_e_salva_11, label_visibility="collapsed")

                st.markdown("<div style='margin-bottom: 5px;'></div>", unsafe_allow_html=True)

                link_11 = st.text_area(
                    "Link/Evidência da composição da equipe (1.1):", 
                    value=evidencia_11_salva, 
                    key=f"l_11_txt_area_{ano_sel}", 
                    on_change=cb_processa_e_salva_11,
                    placeholder="Cole aqui o link do decreto de lotação de pessoal, relatório do setor de RH ou folha simplificada da TI...",
                    height=90
                )

                placeholder_links_11 = st.empty()
                links_11_visuais = [u[0] for u in re.findall(regex_pure_url, link_11 or "")]
                if links_11_visuais:
                    placeholder_links_11.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_11_visuais]))

                # Resumo dinâmico e impacto de pontuação
                total_pessoal = int(d11.get("valor", "0"))
                pts_atuais_11 = d11.get("pontos", 0.0)
                cor_txt_11 = "#28a745" if pts_atuais_11 == 30.0 else "#6c757d"
                
                st.info(f"👥 Total de Pessoal Efetivo Computado (C+Co+E): {total_pessoal} funcionário(s)")
                st.markdown(f"<span style='color:{cor_txt_11}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.1: +{pts_atuais_11:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.1", res_data, ano_sel)

        # GATILHO DO MODAL 1.1
        if st.session_state.get(f"gatilho_modal_1_1_{ano_sel}", False):
            modal_aviso_link("1.1", st.session_state.get(f"links_pendentes_1_1_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_1_{ano_sel}"] = False

            # =============================================================================
        # QUESITO 1.2 • ATRIBUIÇÕES DO SETOR DE TIC (100% INDEPENDENTE)
        # =============================================================================
        regex_pure_url = r'((https?://[^\s<>"]+))'

        with st.container(key=f"container_bloco_compdec_1_2_final_{ano_sel}", border=True):
            with st.expander(f"📌 Quesito 1.2 - Definição de Atribuições Formais da Equipe", expanded=True):
                st.subheader("1.2 • Atribuições Formais")
                st.write("**A prefeitura municipal definiu formalmente as atribuições do pessoal do setor de Tecnologia da Informação e Comunicação (TIC)?**")
                st.caption("ℹ *Salvamento automático por callbacks nativos de estado com validação de link.*")
                
                opcoes12 = ["Selecione...", "Sim – 30", "Não – 00"]
                
                # Recupera o estado salvo no dicionário de dados históricos
                d12 = res_data.get("1.2", {"valor": "Selecione...", "pontos": 0.0, "link": ""})
                if d12 is None: d12 = {"valor": "Selecione...", "pontos": 0.0, "link": ""}
                
                v_salvo_12 = d12.get("valor", "Selecione...")
                chave_radio_12 = f"r_12_{v_salvo_12}_{ano_sel}"

                def cb_radio_12():
                    val = st.session_state[chave_radio_12]
                    pts = 30.0 if "Sim" in val else 0.0
                    lnk = st.session_state.get(f"l_12_txt_{ano_sel}", d12.get("link", ""))
                    
                    save_resp("1.2", val, pts, lnk)
                    res_data["1.2"] = {"valor": val, "pontos": pts, "link": lnk}

                def cb_text_12():
                    lnk = st.session_state[f"l_12_txt_{ano_sel}"]
                    val = st.session_state.get(chave_radio_12, v_salvo_12)
                    pts = 30.0 if "Sim" in val else 0.0
                    
                    save_resp("1.2", val, pts, lnk)
                    res_data["1.2"] = {"valor": val, "pontos": pts, "link": lnk}
                    
                    links_atuais = [u[0] for u in re.findall(regex_pure_url, lnk or "")]
                    links_antigos = [u[0] for u in re.findall(regex_pure_url, d12.get("link", "") or "")]
                    
                    if lnk != d12.get("link", "") and links_atuais:
                        if links_atuais != links_antigos:
                            st.session_state[f"links_pendentes_1_2_{ano_sel}"] = links_atuais
                            st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = True

                col1, col2 = st.columns([1, 1])
                with col1:
                    idx12 = opcoes12.index(v_salvo_12) if v_salvo_12 in opcoes12 else 0
                    st.radio(
                        "Selecione 1.2:", 
                        options=opcoes12, 
                        index=idx12, 
                        key=chave_radio_12,
                        on_change=cb_radio_12,
                        label_visibility="collapsed"
                    )
                    
                with col2:
                    link_12 = st.text_area(
                        "Link/Evidência (1.2):", 
                        value=d12.get("link", ""), 
                        key=f"l_12_txt_{ano_sel}", 
                        on_change=cb_text_12, 
                        placeholder="Insira o link do manual de cargos, decreto de atribuições de secretarias ou manual interno de procedimentos...",
                        height=100
                    )
                    placeholder_links_12 = st.empty()
                    links_12_visuais = [u[0] for u in re.findall(regex_pure_url, link_12 or "")]
                    if links_12_visuais:
                        placeholder_links_12.markdown(f"**Links Ativos:** " + " | ".join([f"🔗 [{u}]({u})" for u in links_12_visuais]))

                pts_atuais_12 = d12.get("pontos", 0.0)
                cor_txt_12 = "#28a745" if pts_atuais_12 == 30.0 else "#6c757d"
                st.markdown(f"<span style='color:{cor_txt_12}; font-weight:bold;'>📊 Impacto de Pontuação no Quesito 1.2: +{pts_atuais_12:.1f} pontos</span>", unsafe_allow_html=True)
                bloco_comentarios("1.2", res_data, ano_sel)

        # GATILHO DO MODAL 1.2
        if st.session_state.get(f"gatilho_modal_1_2_{ano_sel}", False):
            modal_aviso_link("1.2", st.session_state.get(f"links_pendentes_1_2_{ano_sel}", []))
            st.session_state[f"gatilho_modal_1_2_{ano_sel}"] = False



