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
# PEGA A CHAVE DO SECRETS (JÁ CONFIGURADO)
# ==========================================

def get_api_key():
    """Pega a chave do Streamlit Secrets"""
    try:
        if hasattr(st, 'secrets') and 'OCR_API_KEY' in st.secrets:
            return st.secrets['OCR_API_KEY']
    except:
        pass
    return None

# ==========================================
# CONFIGURAÇÕES
# ==========================================
API_URL = "https://api.ocr.space/parse/image"
DB_FILE = "gabaritos_historico.json"

# Tenta importar OCR local (fallback)
try:
    import pytesseract
    import cv2
    import numpy as np
    OCR_LOCAL = True
except:
    OCR_LOCAL = False

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

def processar_com_api(imagem):
    try:
        api_key = get_api_key()
        if not api_key:
            return {}
        
        img_bytes = io.BytesIO()
        imagem.save(img_bytes, format='PNG')
        img_bytes = img_bytes.getvalue()
        
        files = {'file': ('image.png', img_bytes, 'image/png')}
        data = {
            'apikey': api_key,
            'language': 'por',
            'isOverlayRequired': False,
            'OCREngine': 2
        }
        
        with st.spinner('Processando com OCR...'):
            response = requests.post(API_URL, files=files, data=data, timeout=30)
        
        if response.status_code == 200:
            resultado = response.json()
            texto = ""
            for pagina in resultado.get('ParsedResults', []):
                texto += pagina.get('ParsedText', '') + "\n"
            return extrair_respostas(texto)
        return {}
    except Exception as e:
        st.error(f"Erro: {str(e)}")
        return {}

def processar_local(imagem):
    if not OCR_LOCAL:
        return {}
    try:
        img_array = np.array(imagem)
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
        
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDE0123456789'
        texto = pytesseract.image_to_string(thresh, config=custom_config)
        return extrair_respostas(texto)
    except:
        return {}

def extrair_respostas(texto):
    respostas = {}
    texto = texto.upper().strip()
    linhas = texto.split('\n')
    
    padrao = re.compile(r'(\d+)\s*[-.:]?\s*([A-E])')
    
    for linha in linhas:
        match = padrao.search(linha)
        if match:
            num = int(match.group(1))
            letra = match.group(2).upper()
            if 1 <= num <= 50:
                respostas[str(num)] = letra
    
    if not respostas:
        letras = []
        for linha in linhas:
            for char in linha:
                if char in 'ABCDE':
                    letras.append(char)
        for i, letra in enumerate(letras[:50], 1):
            respostas[str(i)] = letra
    
    return respostas

def corrigir(respostas_aluno, gabarito, nome_prova=""):
    acertos = 0
    total = len(gabarito)
    detalhes = []
    nao_respondidas = 0
    
    # Ordenar questões para exibição correta
    questoes_ordenadas = sorted(gabarito.keys(), key=lambda x: int(x))
    
    for q in questoes_ordenadas:
        gab_correto = gabarito[q]
        resp_al = respostas_aluno.get(q, "-")
        
        if resp_al == "-":
            status = "❌ Não respondida"
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
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("🎯 Nota", f"{nota:.1f}%")
    with col2:
        st.metric("✅ Acertos", acertos)
    with col3:
        st.metric("❌ Erros", total - acertos - nao_respondidas)
    
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
    if st.button("📥 Exportar CSV"):
        df_export = pd.DataFrame(detalhes)
        csv = df_export.to_csv(index=False)
        st.download_button(
            "Baixar CSV",
            csv,
            f"correcao_{timestamp}.csv",
            "text/csv"
        )

# ==========================================
# FUNÇÃO PARA CRIAR COLUNAS EM ORDEM
# ==========================================
def criar_colunas_questoes(questoes, gabarito=None, modo="criar"):
    """Cria as questões em ordem correta"""
    resultados = {}
    
    # Calcular quantas colunas usar (2 no celular, 4 no desktop)
    num_colunas = 2  # Padrão para mobile
    
    # Ordenar questões
    questoes_ordenadas = sorted(questoes, key=lambda x: int(x))
    
    # Criar colunas
    cols = st.columns(num_colunas)
    
    for idx, q in enumerate(questoes_ordenadas):
        col_idx = idx % num_colunas
        with cols[col_idx]:
            if modo == "criar":
                resultados[q] = st.selectbox(
                    f"Q{q}",
                    ["A", "B", "C", "D", "E"],
                    key=f"criar_q_{q}"
                )
            else:  # modo correção
                resultados[q] = st.selectbox(
                    f"Q{q}",
                    ["-", "A", "B", "C", "D", "E"],
                    key=f"corrigir_q_{q}"
                )
    
    return resultados

# ==========================================
# INTERFACE
# ==========================================

st.set_page_config(
    page_title="Corretor de Provas",
    page_icon="📝",
    layout="centered"
)

# CSS para melhor visualização mobile
st.markdown("""
    <style>
    /* Ajustes para mobile */
    @media (max-width: 768px) {
        .stSelectbox > div {
            margin-bottom: 10px;
        }
        .stButton > button {
            height: 50px;
            font-size: 16px;
        }
        .stMetric {
            text-align: center;
        }
    }
    /* Melhorar visualização das colunas */
    .row-widget.stColumns {
        gap: 10px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("📝 Corretor de Provas")

# Verifica se a chave está funcionando
api_key = get_api_key()
if api_key:
    st.success("✅ API OCR configurada com sucesso!")
else:
    st.info("📌 Usando OCR local (Tesseract)")

dados = carregar_historico()

aba1, aba2, aba3 = st.tabs(["📌 Gabaritos", "📷 Corrigir", "📊 Histórico"])

# ==========================================
# ABA 1 - GABARITOS (CORRIGIDO)
# ==========================================
with aba1:
    st.subheader("Criar Novo Gabarito")
    
    with st.form("form_gabarito"):
        nome = st.text_input("Nome da Prova", placeholder="Ex: Biologia - Prova 1")
        num = st.number_input("Quantidade de Questões", min_value=1, max_value=50, value=13)
        
        st.write("Selecione as respostas corretas:")
        
        # Criar questões em ordem
        questoes = [str(i) for i in range(1, int(num) + 1)]
        respostas = criar_colunas_questoes(questoes, modo="criar")
        
        if st.form_submit_button("💾 Salvar Gabarito"):
            if nome:
                dados[nome] = respostas
                salvar_historico(dados)
                st.success(f"✅ Gabarito '{nome}' salvo com sucesso!")
                st.rerun()
            else:
                st.error("Digite um nome para a prova")
    
    st.markdown("---")
    st.subheader("📂 Gabaritos Salvos")
    
    if dados:
        for nome, gab in sorted(dados.items()):
            with st.expander(f"📄 {nome} ({len(gab)} questões)"):
                # Ordenar para exibição
                gab_ordenado = dict(sorted(gab.items(), key=lambda x: int(x[0])))
                df = pd.DataFrame(list(gab_ordenado.items()), columns=["Questão", "Resposta"])
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                if st.button(f"🗑️ Excluir {nome}", key=f"del_{nome}"):
                    del dados[nome]
                    salvar_historico(dados)
                    st.rerun()
    else:
        st.info("Nenhum gabarito cadastrado ainda")

# ==========================================
# ABA 2 - CORRIGIR (CORRIGIDO)
# ==========================================
with aba2:
    if not dados:
        st.warning("⚠️ Crie um gabarito na aba 'Gabaritos' primeiro")
    else:
        prova = st.selectbox("Selecione o Gabarito", list(dados.keys()))
        gabarito = dados[prova]
        
        metodo = st.radio(
            "Como deseja inserir as respostas?",
            ["📷 Foto", "⌨️ Digitar", "📋 Colar"],
            horizontal=True
        )
        
        if metodo == "📷 Foto":
            st.write("Tire uma foto da folha de respostas:")
            foto = st.camera_input("📸 Capturar")
            
            if foto:
                imagem = Image.open(foto)
                st.image(imagem, caption="Foto enviada", use_container_width=True)
                
                with st.spinner("🔍 Reconhecendo respostas..."):
                    respostas = processar_com_api(imagem)
                    if not respostas and OCR_LOCAL:
                        respostas = processar_local(imagem)
                
                if respostas:
                    st.success(f"✅ Encontradas {len(respostas)} respostas!")
                    # Ordenar para exibição
                    respostas_ordenadas = dict(sorted(respostas.items(), key=lambda x: int(x[0])))
                    df = pd.DataFrame(list(respostas_ordenadas.items()), columns=["Questão", "Resposta"])
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    
                    if st.button("📊 Corrigir Prova", type="primary"):
                        corrigir(respostas, gabarito, prova)
                else:
                    st.warning("⚠️ Não foi possível reconhecer as respostas")
                    st.info("💡 Tente: tirar uma foto mais nítida ou digitar manualmente")
        
        elif metodo == "⌨️ Digitar":
            st.write("Digite as respostas do aluno:")
            
            # Criar questões em ordem para correção
            questoes = sorted(gabarito.keys(), key=lambda x: int(x))
            respostas = criar_colunas_questoes(questoes, modo="corrigir")
            
            if st.button("📊 Corrigir Prova", type="primary"):
                corrigir(respostas, gabarito, prova)
        
        else:  # Colar
            st.write("Cole as respostas (ex: 1A, 2B, 3C...):")
            texto = st.text_area(
                "Respostas",
                placeholder="1A\n2B\n3C\n4D\n5E",
                height=100
            )
            
            if texto:
                respostas = extrair_respostas(texto)
                if respostas:
                    st.success(f"✅ Identificadas {len(respostas)} respostas!")
                    # Ordenar para exibição
                    respostas_ordenadas = dict(sorted(respostas.items(), key=lambda x: int(x[0])))
                    df = pd.DataFrame(list(respostas_ordenadas.items()), columns=["Questão", "Resposta"])
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    
                    if st.button("📊 Corrigir Prova", type="primary"):
                        corrigir(respostas, gabarito, prova)
                else:
                    st.warning("⚠️ Não foi possível identificar as respostas")

# ==========================================
# ABA 3 - HISTÓRICO
# ==========================================
with aba3:
    st.subheader("📊 Histórico de Correções")
    
    if 'historico' in st.session_state and st.session_state.historico:
        st.info(f"Total de correções: {len(st.session_state.historico)}")
        
        for item in reversed(st.session_state.historico):
            with st.expander(f"📝 {item['prova']} - {item['data']}"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Nota", f"{item['nota']:.1f}%")
                with col2:
                    st.metric("Acertos", f"{item['acertos']}/{item['total']}")
                with col3:
                    st.metric("Não respondidas", item['nao_respondidas'])
                
                df = pd.DataFrame(item['detalhes'])
                st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma correção realizada ainda")

st.markdown("---")
st.caption("📝 Corretor de Provas v2.0 - Otimizado para celular")
