import json
import os
import pandas as pd
import streamlit as st
from PIL import Image
import re
from datetime import datetime
import io
import requests
import base64

# ==========================================
# CONFIGURAÇÃO SEGURA DA API DE OCR
# ==========================================
# NUNCA coloque a chave diretamente no código!
# Use st.secrets para armazenar informações sensíveis

def get_api_key():
    """Obtém a chave da API de forma segura"""
    # Tenta obter do st.secrets (Streamlit Cloud)
    if hasattr(st, 'secrets') and 'OCR_API_KEY' in st.secrets:
        return st.secrets['OCR_API_KEY']
    
    # Fallback para variável de ambiente (desenvolvimento local)
    api_key = os.environ.get('OCR_API_KEY')
    if api_key:
        return api_key
    
    # Último recurso: NUNCA use chaves hardcoded!
    st.error("❌ Chave de API não encontrada! Configure st.secrets ou variáveis de ambiente.")
    return None

# ==========================================
# CONFIGURAÇÃO DA API
# ==========================================
API_URL = "https://api.ocr.space/parse/image"

# Arquivo JSON local para salvar o histórico de gabaritos
DB_FILE = "gabaritos_historico.json"

# Tentar importar bibliotecas locais de OCR com fallback
try:
    import pytesseract
    import cv2
    import numpy as np
    OCR_LOCAL_DISPONIVEL = True
except ImportError:
    OCR_LOCAL_DISPONIVEL = False

# ==========================================
# FUNÇÕES PRINCIPAIS
# ==========================================

def carregar_historico():
    """Carrega o histórico de gabaritos do arquivo JSON"""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def salvar_historico(dados):
    """Salva o histórico de gabaritos no arquivo JSON"""
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=4)
        return True
    except:
        return False

def processar_imagem_com_api_ocr(imagem):
    """
    Processa a imagem usando a API OCR.Space
    """
    try:
        api_key = get_api_key()
        if not api_key:
            return {}
        
        # Converter PIL Image para bytes
        img_bytes = io.BytesIO()
        imagem.save(img_bytes, format='PNG')
        img_bytes = img_bytes.getvalue()
        
        # Preparar para envio
        files = {
            'file': ('image.png', img_bytes, 'image/png')
        }
        
        data = {
            'apikey': api_key,
            'language': 'por',
            'isOverlayRequired': False,
            'detectOrientation': True,
            'scale': True,
            'OCREngine': 2
        }
        
        # Fazer requisição para a API
        with st.spinner('📡 Processando imagem com OCR online...'):
            response = requests.post(API_URL, files=files, data=data, timeout=30)
            
        if response.status_code == 200:
            resultado = response.json()
            
            if resultado.get('IsErroredOnProcessing'):
                st.error(f"Erro na API: {resultado.get('ErrorMessage', 'Erro desconhecido')}")
                return {}
            
            # Extrair texto do resultado
            texto_completo = ""
            for pagina in resultado.get('ParsedResults', []):
                texto_completo += pagina.get('ParsedText', '') + "\n"
            
            if texto_completo.strip():
                return extrair_respostas_do_texto(texto_completo)
            else:
                st.warning("⚠️ Nenhum texto foi reconhecido na imagem.")
                return {}
        else:
            st.error(f"Erro na API: Status {response.status_code}")
            return {}
            
    except Exception as e:
        st.error(f"Erro ao processar imagem com API: {str(e)}")
        return {}

def processar_imagem_local(imagem):
    """
    Processa a imagem usando Tesseract local (fallback)
    """
    if not OCR_LOCAL_DISPONIVEL:
        return {}
    
    try:
        # Converter PIL Image para OpenCV
        img_array = np.array(imagem)
        
        # Converter para escala de cinza
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
        
        # Redimensionar para melhorar performance
        height, width = gray.shape
        if width > 2000:
            scale = 2000 / width
            new_width = 2000
            new_height = int(height * scale)
            gray = cv2.resize(gray, (new_width, new_height))
        
        # Aplicar threshold para melhorar contraste
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        # Remover ruídos
        kernel = np.ones((2, 2), np.uint8)
        thresh = cv2.erode(thresh, kernel, iterations=1)
        thresh = cv2.dilate(thresh, kernel, iterations=1)
        
        # Configuração do Tesseract
        custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDE0123456789'
        texto = pytesseract.image_to_string(thresh, config=custom_config)
        
        return extrair_respostas_do_texto(texto)
        
    except Exception as e:
        st.error(f"Erro no OCR local: {str(e)}")
        return {}

def processar_imagem_para_respostas(imagem):
    """
    Tenta processar com a API primeiro, fallback para local se falhar
    """
    # Primeiro tenta com a API
    respostas = processar_imagem_com_api_ocr(imagem)
    
    # Se falhar, tenta com OCR local
    if not respostas and OCR_LOCAL_DISPONIVEL:
        st.info("🔄 Tentando OCR local...")
        respostas = processar_imagem_local(imagem)
    
    return respostas

def extrair_respostas_do_texto(texto):
    """
    Extrai respostas do texto usando múltiplos padrões
    """
    respostas = {}
    
    # Limpar texto
    texto = texto.upper().strip()
    linhas = texto.split('\n')
    
    # Padrões de reconhecimento
    padroes = [
        re.compile(r'(?:Q|QUESTÃO)\s*(\d+)\s*[.:)]?\s*([A-E])'),
        re.compile(r'(\d+)\s*[-.:]?\s*([A-E])'),
        re.compile(r'(\d+)\s*[.:)]\s*([A-E])'),
        re.compile(r'(\d+)\s*[-–—]\s*([A-E])'),
        re.compile(r'(\d+)\s*[.)]\s*([A-E])'),
        re.compile(r'ALT(?:ERNATIVA)?\s*([A-E])', re.IGNORECASE),
    ]
    
    respostas_encontradas = {}
    numeros_encontrados = set()
    
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue
            
        for padrao in padroes:
            match = padrao.search(linha)
            if match:
                try:
                    if len(match.groups()) == 2:
                        num = int(match.group(1))
                        letra = match.group(2).upper()
                    else:
                        letra = match.group(1).upper()
                        num = max([0] + list(numeros_encontrados)) + 1
                    
                    if 1 <= num <= 50 and letra in 'ABCDE':
                        respostas_encontradas[str(num)] = letra
                        numeros_encontrados.add(num)
                        break
                except:
                    continue
    
    if respostas_encontradas:
        return respostas_encontradas
    
    # Tentar identificar sequência de letras
    letras_sequencia = []
    for linha in linhas:
        linha = linha.strip()
        if len(linha) == 1 and linha in 'ABCDE':
            letras_sequencia.append(linha)
        elif len(linha) > 1:
            for char in linha:
                if char in 'ABCDE':
                    letras_sequencia.append(char)
    
    if letras_sequencia:
        for i, letra in enumerate(letras_sequencia[:50], 1):
            respostas[str(i)] = letra
        return respostas
    
    letras_isoladas = re.findall(r'\b([A-E])\b', texto)
    if letras_isoladas:
        for i, letra in enumerate(letras_isoladas[:50], 1):
            respostas[str(i)] = letra
        return respostas
    
    return {}

def calcular_correcao(respostas_aluno, gabarito_oficial, nome_prova=""):
    """Calcula e exibe os resultados da correção"""
    acertos = 0
    total_questoes = len(gabarito_oficial)
    detalhes = []
    questoes_nao_respondidas = 0
    
    respostas_validas = {}
    for q, resp in respostas_aluno.items():
        if resp and resp != "-" and resp != "":
            respostas_validas[q] = resp
    
    for q, gab_correto in gabarito_oficial.items():
        resp_al = respostas_validas.get(q, "-")
        
        if resp_al == "-":
            status = "⬜ Não respondida"
            questoes_nao_respondidas += 1
        elif resp_al == gab_correto:
            acertos += 1
            status = "✅ Correto"
        else:
            status = f"❌ Errado (Era {gab_correto})"
        
        detalhes.append({
            "Questão": f"Q{q}",
            "Gabarito": gab_correto,
            "Resposta": resp_al,
            "Status": status,
        })
    
    nota_final = (acertos / total_questoes) * 100
    
    st.markdown("---")
    st.subheader("📊 Resultado da Correção")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📈 Nota", f"{nota_final:.1f}%")
    with col2:
        st.metric("✅ Acertos", acertos)
    with col3:
        st.metric("❌ Erros", total_questoes - acertos - questoes_nao_respondidas)
    with col4:
        st.metric("⬜ Em branco", questoes_nao_respondidas)
    
    df_detalhes = pd.DataFrame(detalhes)
    st.dataframe(df_detalhes, use_container_width=True, hide_index=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    resultado = {
        "data": timestamp,
        "prova": nome_prova,
        "nota": nota_final,
        "acertos": acertos,
        "total": total_questoes,
        "nao_respondidas": questoes_nao_respondidas,
        "detalhes": detalhes
    }
    
    if 'historico_correcoes' not in st.session_state:
        st.session_state.historico_correcoes = []
    st.session_state.historico_correcoes.append(resultado)
    
    col_export, col_print = st.columns(2)
    with col_export:
        if st.button("📥 Exportar CSV"):
            df_export = pd.DataFrame(detalhes)
            csv = df_export.to_csv(index=False)
            st.download_button(
                label="Baixar CSV",
                data=csv,
                file_name=f"correcao_{timestamp}.csv",
                mime="text/csv"
            )
    
    return resultado

# ==========================================
# INTERFACE STREAMLIT
# ==========================================

st.set_page_config(
    page_title="Corretor de Provas", 
    page_icon="📝", 
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.title("📝 Corretor de Provas")
st.caption("Versão 2.1 - Com OCR via API e reconhecimento automático")

# Verificar se a chave API está configurada
api_key = get_api_key()
if not api_key:
    st.warning("""
    ⚠️ **Chave de API não configurada!**
    
    Configure a chave de API de uma das seguintes formas:
    1. **Streamlit Cloud**: Crie um arquivo `.streamlit/secrets.toml` com:
       ```toml
       OCR_API_KEY = "sua_chave_aqui"
