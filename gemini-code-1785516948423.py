import json
import os
import pandas as pd
import streamlit as st
from PIL import Image
import re
from datetime import datetime
import io
import requests

# ==========================================
# CONFIGURAÇÃO DA API
# ==========================================

def get_api_key():
    """Pega a chave do Streamlit Secrets"""
    try:
        if hasattr(st, 'secrets') and 'OCR_API_KEY' in st.secrets:
            return st.secrets['OCR_API_KEY']
    except:
        pass
    return None

API_URL = "https://api.ocr.space/parse/image"
DB_FILE = "gabaritos_historico.json"

# Tenta importar OCR local
try:
    import pytesseract
    import cv2
    import numpy as np
    OCR_LOCAL = True
except:
    OCR_LOCAL = False

# ==========================================
# FUNÇÕES PRINCIPAIS
# ==========================================

def carregar_historico():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def salvar_historico(dados):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=4)
        return True
    except:
        return False

def processar_imagem_api(imagem):
    """Processa imagem com OCR.Space API"""
    try:
        api_key = get_api_key()
        if not api_key:
            return {}
        
        # Converter para bytes
        img_bytes = io.BytesIO()
        imagem.save(img_bytes, format='PNG')
        img_bytes = img_bytes.getvalue()
        
        files = {'file': ('image.png', img_bytes, 'image/png')}
        data = {
            'apikey': api_key,
            'language': 'por',
            'isOverlayRequired': False,
            'detectOrientation': True,
            'scale': True,
            'OCREngine': 2,
            'filetype': 'PNG'
        }
        
        with st.spinner('📡 Processando com OCR online...'):
            response = requests.post(API_URL, files=files, data=data, timeout=30)
        
        if response.status_code == 200:
            resultado = response.json()
            
            if resultado.get('IsErroredOnProcessing'):
                st.error(f"Erro: {resultado.get('ErrorMessage', 'Erro desconhecido')}")
                return {}
            
            texto_completo = ""
            for pagina in resultado.get('ParsedResults', []):
                texto_completo += pagina.get('ParsedText', '') + "\n"
            
            if texto_completo.strip():
                return extrair_respostas(texto_completo)
            return {}
        return {}
    except Exception as e:
        st.error(f"Erro na API: {str(e)}")
        return {}

def processar_imagem_local(imagem):
    """Processa imagem com Tesseract local"""
    if not OCR_LOCAL:
        return {}
    try:
        img_array = np.array(imagem)
        
        # Converter para cinza
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
        
        # Redimensionar para melhorar
        height, width = gray.shape
        if width > 2000:
            scale = 2000 / width
            new_width = 2000
            new_height = int(height * scale)
            gray = cv2.resize(gray, (new_width, new_height))
        
        # Melhorar contraste
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        # Remover ruído
        kernel = np.ones((2, 2), np.uint8)
        thresh = cv2.erode(thresh, kernel, iterations=1)
        thresh = cv2.dilate(thresh, kernel, iterations=1)
        
        # Configurar Tesseract
        custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEabcde0123456789'
        texto = pytesseract.image_to_string(thresh, config=custom_config, lang='por')
        
        return extrair_respostas(texto)
    except Exception as e:
        st.error(f"Erro no OCR local: {str(e)}")
        return {}

def extrair_respostas(texto):
    """Extrai respostas do texto de forma mais robusta"""
    respostas = {}
    
    # Limpar texto
    texto = texto.strip()
    
    # Padrões para encontrar respostas
    padroes = [
        # Padrão: "1 a" ou "1a" ou "1 - a"
        re.compile(r'(\d+)\s*[-.:)]?\s*([A-Ea-e])'),
        # Padrão: "Q1 a" ou "Questão 1 a"
        re.compile(r'(?:Q|QUESTÃO)\s*(\d+)\s*[-.:)]?\s*([A-Ea-e])'),
        # Padrão: "1) a" ou "1. a"
        re.compile(r'(\d+)\s*[.)]\s*([A-Ea-e])'),
        # Padrão: "a)" ou "a." (sem número, usa sequência)
        re.compile(r'([A-Ea-e])\s*[.)]'),
    ]
    
    # Tentar cada padrão
    for padrao in padroes:
        matches = padrao.findall(texto)
        if matches:
            for match in matches:
                if len(match) == 2:
                    num = int(match[0])
                    letra = match[1].upper()
                    if 1 <= num <= 50 and letra in 'ABCDE':
                        respostas[str(num)] = letra
                else:
                    # Apenas letra (sequencial)
                    letra = match[0].upper()
                    if letra in 'ABCDE':
                        num = len(respostas) + 1
                        if num <= 50:
                            respostas[str(num)] = letra
            
            # Se encontrou algo, retorna
            if respostas:
                return respostas
    
    # Última tentativa: procurar letras soltas
    letras = re.findall(r'\b([A-Ea-e])\b', texto)
    if letras:
        for i, letra in enumerate(letras[:50], 1):
            respostas[str(i)] = letra.upper()
        return respostas
    
    return respostas

def corrigir_prova(respostas_aluno, gabarito, nome_prova=""):
    """Corrige a prova e exibe resultados"""
    # Ordenar questões
    questoes_ordenadas = sorted(gabarito.keys(), key=lambda x: int(x))
    
    acertos = 0
    total = len(questoes_ordenadas)
    detalhes = []
    nao_respondidas = 0
    
    for q in questoes_ordenadas:
        gab_correto = gabarito[q]
        resp_al = respostas_aluno.get(q, "-")
        
        if resp_al == "-" or resp_al == "":
            status = "⬜ Não respondida"
            nao_respondidas += 1
        elif resp_al == gab_correto:
            acertos += 1
            status = "✅ Correta"
        else:
            status = f"❌ Errada (era {gab_correto})"
        
        detalhes.append({
            "Questão": f"Q{q}",
            "Gabarito": gab_correto,
            "Resposta": resp_al,
            "Status": status,
        })
    
    nota = (acertos / total) * 100
    
    st.markdown("---")
    st.subheader("📊 Resultado da Correção")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🎯 Nota", f"{nota:.1f}%")
    with col2:
        st.metric("✅ Acertos", acertos)
    with col3:
        st.metric("❌ Erros", total - acertos - nao_respondidas)
    with col4:
        st.metric("⬜ Em branco", nao_respondidas)
    
    df = pd.DataFrame(detalhes)
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Salvar histórico
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if 'historico' not in st.session_state:
        st.session_state.historico = []
    st.session_state.historico.append({
        "data": timestamp,
        "prova": nome_prova,
        "nota": nota,
        "acertos": acertos,
        "total": total,
        "nao_respondidas": nao_respondidas,
        "detalhes": detalhes
    })
    
    # Exportar CSV
    col_export, col_limpar = st.columns(2)
    with col_export:
        if st.button("📥 Exportar CSV"):
            df_export = pd.DataFrame(detalhes)
            csv = df_export.to_csv(index=False)
            st.download_button(
                "Baixar CSV",
                csv,
                f"correcao_{timestamp}.csv",
                "text/csv"
            )
    
    with col_limpar:
        if st.button("🔄 Nova Correção"):
            st.rerun()

# ==========================================
# FUNÇÃO PARA CRIAR QUESTÕES EM ORDEM
# ==========================================
def criar_questoes_ordenadas(num_questoes, modo="criar", gabarito=None):
    """Cria questões em ordem com 2 colunas (mobile) ou 4 colunas (desktop)"""
    resultados = {}
    
    # Detectar se é mobile (tela pequena)
    is_mobile = st.session_state.get('is_mobile', False)
    num_colunas = 2 if is_mobile else 4
    
    # Criar lista de questões
    questoes = list(range(1, num_questoes + 1))
    
    # Dividir em colunas de forma ordenada
    colunas = [[] for _ in range(num_colunas)]
    for i, q in enumerate(questoes):
        colunas[i % num_colunas].append(q)
    
    # Criar colunas no Streamlit
    cols = st.columns(num_colunas)
    
    for col_idx, col in enumerate(cols):
        with col:
            for q in colunas[col_idx]:
                if modo == "criar":
                    resultados[str(q)] = st.selectbox(
                        f"Q{q}",
                        ["A", "B", "C", "D", "E"],
                        key=f"criar_q_{q}"
                    )
                else:  # modo correção
                    respostas_opcoes = ["-", "A", "B", "C", "D", "E"]
                    valor_default = 0
                    if gabarito and str(q) in gabarito:
                        valor_default = respostas_opcoes.index(gabarito[str(q)])
                    resultados[str(q)] = st.selectbox(
                        f"Q{q}",
                        respostas_opcoes,
                        key=f"corrigir_q_{q}"
                    )
    
    return resultados

# ==========================================
# INTERFACE STREAMLIT
# ==========================================

st.set_page_config(
    page_title="Corretor de Provas",
    page_icon="📝",
    layout="centered"
)

# CSS para mobile
st.markdown("""
    <style>
    /* Responsivo */
    @media (max-width: 768px) {
        .stSelectbox > div {
            margin-bottom: 8px;
        }
        .stButton > button {
            height: 50px;
            font-size: 16px;
        }
        .stMetric {
            text-align: center;
        }
        .stColumns {
            gap: 5px;
        }
        .stSelectbox label {
            font-size: 14px;
        }
    }
    /* Melhorar visualização */
    .stAlert {
        padding: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# Detectar se é mobile
if 'is_mobile' not in st.session_state:
    # Por padrão, assumimos que é mobile (melhor visualização)
    st.session_state.is_mobile = True

st.title("📝 Corretor de Provas")

# Verificar chave
api_key = get_api_key()
if api_key:
    st.success("✅ API OCR configurada!")
else:
    st.info("📌 Usando OCR local (Tesseract)")

dados = carregar_historico()

# Menu
aba1, aba2, aba3 = st.tabs(["📌 Gabaritos", "📷 Corrigir", "📊 Histórico"])

# ==========================================
# ABA 1 - GABARITOS
# ==========================================
with aba1:
    st.subheader("Criar Gabarito")
    
    with st.form("form_gabarito"):
        nome = st.text_input("Nome da Prova", placeholder="Ex: Biologia - Prova 1")
        num_questoes = st.number_input("Quantidade de Questões", min_value=1, max_value=50, value=13)
        
        st.write("Selecione as respostas corretas:")
        
        # Criar questões em ordem
        respostas = criar_questoes_ordenadas(int(num_questoes), modo="criar")
        
        if st.form_submit_button("💾 Salvar Gabarito"):
            if nome and nome.strip():
                if nome in dados:
                    st.warning(f"Gabarito '{nome}' já existe. Deseja sobrescrever?")
                    if st.button("Sim, sobrescrever"):
                        dados[nome] = respostas
                        salvar_historico(dados)
                        st.success(f"✅ Gabarito '{nome}' atualizado!")
                        st.rerun()
                else:
                    dados[nome] = respostas
                    salvar_historico(dados)
                    st.success(f"✅ Gabarito '{nome}' salvo!")
                    st.rerun()
            else:
                st.error("Digite um nome para a prova")
    
    st.markdown("---")
    st.subheader("📂 Gabaritos Salvos")
    
    if dados:
        for nome in sorted(dados.keys()):
            gabarito = dados[nome]
            with st.expander(f"📄 {nome} ({len(gabarito)} questões)"):
                # Ordenar para exibição
                gab_ordenado = dict(sorted(gabarito.items(), key=lambda x: int(x[0])))
                df = pd.DataFrame(list(gab_ordenado.items()), columns=["Questão", "Resposta"])
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"📋 Copiar", key=f"copy_{nome}"):
                        texto = "\n".join([f"{k} {v}" for k, v in gab_ordenado.items()])
                        st.code(texto, language="text")
                with col2:
                    if st.button(f"🗑️ Excluir", key=f"del_{nome}"):
                        del dados[nome]
                        salvar_historico(dados)
                        st.rerun()
    else:
        st.info("Nenhum gabarito cadastrado")

# ==========================================
# ABA 2 - CORRIGIR
# ==========================================
with aba2:
    if not dados:
        st.warning("⚠️ Crie um gabarito primeiro!")
    else:
        # Selecionar prova
        prova_selecionada = st.selectbox(
            "Selecione o Gabarito",
            sorted(dados.keys())
        )
        gabarito = dados[prova_selecionada]
        
        st.info(f"📚 Gabarito: **{prova_selecionada}** - {len(gabarito)} questões")
        
        metodo = st.radio(
            "Como inserir as respostas?",
            ["📷 Foto", "⌨️ Digitar", "📋 Colar"],
            horizontal=True
        )
        
        if metodo == "📷 Foto":
            st.write("Tire uma foto da folha de respostas:")
            foto = st.camera_input("📸 Capturar")
            
            if foto:
                imagem = Image.open(foto)
                st.image(imagem, caption="Foto", use_container_width=True)
                
                # Tentar processar
                respostas = processar_imagem_api(imagem)
                if not respostas and OCR_LOCAL:
                    respostas = processar_imagem_local(imagem)
                
                if respostas:
                    st.success(f"✅ Encontradas {len(respostas)} respostas!")
                    
                    # Mostrar respostas encontradas
                    resp_ordenadas = dict(sorted(respostas.items(), key=lambda x: int(x[0])))
                    df = pd.DataFrame(list(resp_ordenadas.items()), columns=["Questão", "Resposta"])
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    
                    if st.button("📊 Corrigir", type="primary"):
                        corrigir_prova(respostas, gabarito, prova_selecionada)
                else:
                    st.error("❌ Não foi possível reconhecer as respostas")
                    st.info("""
                    💡 **Dicas para melhorar:**
                    - Tire uma foto mais nítida
                    - Mantenha a folha bem iluminada
                    - Evite sombras
                    - Use caneta preta
                    - Escreva em letras maiúsculas
                    """)
                    
                    if st.button("✏️ Digitar manualmente"):
                        st.session_state.modo_manual = True
        
        elif metodo == "⌨️ Digitar":
            st.write("Digite as respostas do aluno:")
            
            # Criar questões em ordem
            respostas_aluno = criar_questoes_ordenadas(
                len(gabarito), 
                modo="corrigir",
                gabarito=gabarito
            )
            
            if st.button("📊 Corrigir", type="primary"):
                corrigir_prova(respostas_aluno, gabarito, prova_selecionada)
        
        else:  # Colar
            st.write("Cole as respostas (ex: 1A, 2B, 3C...):")
            texto = st.text_area(
                "Respostas",
                placeholder="1 A\n2 B\n3 C\n4 A\n5 B",
                height=120
            )
            
            if texto:
                respostas = extrair_respostas(texto)
                if respostas:
                    st.success(f"✅ Identificadas {len(respostas)} respostas!")
                    resp_ordenadas = dict(sorted(respostas.items(), key=lambda x: int(x[0])))
                    df = pd.DataFrame(list(resp_ordenadas.items()), columns=["Questão", "Resposta"])
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    
                    if st.button("📊 Corrigir", type="primary"):
                        corrigir_prova(respostas, gabarito, prova_selecionada)
                else:
                    st.warning("Não foi possível identificar as respostas")
                    st.info("Use o formato: número + letra (ex: 1A, 2B, 3C)")

# ==========================================
# ABA 3 - HISTÓRICO
# ==========================================
with aba3:
    st.subheader("📊 Histórico de Correções")
    
    if 'historico' in st.session_state and st.session_state.historico:
        st.info(f"Total: {len(st.session_state.historico)} correções")
        
        if st.button("🗑️ Limpar Histórico"):
            st.session_state.historico = []
            st.rerun()
        
        for item in reversed(st.session_state.historico):
            with st.expander(f"📝 {item['prova']} - {item['data']}"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Nota", f"{item['nota']:.1f}%")
                with col2:
                    st.metric("Acertos", f"{item['acertos']}/{item['total']}")
                with col3:
                    st.metric("Em branco", item['nao_respondidas'])
                
                df = pd.DataFrame(item['detalhes'])
                st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma correção realizada ainda")

st.markdown("---")
st.caption("📝 Corretor de Provas v2.0")
