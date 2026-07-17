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

def mostrar_formulario_gov():
    import streamlit as st
    
    st.title("📊 Questionário i-Gov TI")
    st.write("Bem-vindo ao formulário de Governança de Tecnologia da Informação.")
    
    # Aqui você pode construir as perguntas do seu formulário
    # Exemplo simples:
    opcao = st.radio("A instituição possui Plano Diretor de TI (PDTI)?", ["Sim", "Não"])
    
    if st.button("Salvar Respostas"):
        st.success("Dados salvos com sucesso!")


