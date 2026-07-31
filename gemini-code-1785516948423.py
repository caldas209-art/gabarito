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
# CONFIGURAÇÃO SEGURA DA API - SEM CHAVES NO CÓDIGO!
# ==========================================

def get_api_key():
    """Obtém a chave da API de forma SEGURA"""
    # Tenta obter do st.secrets (Streamlit Cloud)
    if hasattr(st, 'secrets') and 'OCR_API_KEY' in st.secrets:
        return st.secrets['OCR_API_KEY']
    
    # Tenta obter de variável de ambiente (desenvolvimento local)
    api_key = os.environ.get('OCR_API_KEY')
    if api_key:
        return api_key
    
    # Tenta obter de arquivo .env (apenas desenvolvimento local)
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return os.environ.get('OCR_API_KEY')
    except:
        pass
    
    # Se não encontrar, retorna None (usará OCR local)
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
    """Processa a imagem usando a API OCR.Space"""
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
        with st.spinner('Processando imagem com OCR online...'):
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
                st.warning("Nenhum texto foi reconhecido na imagem.")
                return {}
        else:
            st.error(f"Erro na API: Status {response.status_code}")
            return {}
            
    except Exception as e:
        st.error(f"Erro ao processar imagem com API: {str(e)}")
        return {}

def processar_imagem_local(imagem):
    """Processa a imagem usando Tesseract local (fallback)"""
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
    """Tenta processar com a API primeiro, fallback para local se falhar"""
    # Primeiro tenta com a API
    respostas = processar_imagem_com_api_ocr(imagem)
    
    # Se falhar, tenta com OCR local
    if not respostas and OCR_LOCAL_DISPONIVEL:
        st.info("Tentando OCR local...")
        respostas = processar_imagem_local(imagem)
    
    return respostas

def extrair_respostas_do_texto(texto):
    """Extrai respostas do texto usando múltiplos padrões"""
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
    
    # Filtrar respostas não marcadas
    respostas_validas = {}
    for q, resp in respostas_aluno.items():
        if resp and resp != "-" and resp != "":
            respostas_validas[q] = resp
    
    # Verificar cada questão
    for q, gab_correto in gabarito_oficial.items():
        resp_al = respostas_validas.get(q, "-")
        
        if resp_al == "-":
            status = "Nao respondida"
            questoes_nao_respondidas += 1
        elif resp_al == gab_correto:
            acertos += 1
            status = "Correto"
        else:
            status = f"Errado (Era {gab_correto})"
        
        detalhes.append({
            "Questão": f"Q{q}",
            "Gabarito": gab_correto,
            "Resposta": resp_al,
            "Status": status,
        })
    
    nota_final = (acertos / total_questoes) * 100
    
    # Exibir resultados
    st.markdown("---")
    st.subheader("Resultado da Correção")
    
    # Cards com métricas
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Nota", f"{nota_final:.1f}%")
    with col2:
        st.metric("Acertos", acertos)
    with col3:
        st.metric("Erros", total_questoes - acertos - questoes_nao_respondidas)
    with col4:
        st.metric("Em branco", questoes_nao_respondidas)
    
    # Tabela detalhada
    df_detalhes = pd.DataFrame(detalhes)
    st.dataframe(df_detalhes, use_container_width=True, hide_index=True)
    
    # Salvar resultado automaticamente
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
    
    # Botão para exportar resultado
    if st.button("Exportar CSV"):
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

# Estilização CSS
st.markdown("""
<style>
.main { background-color: #f8f9fa; }
.stButton>button { width: 100%; border-radius: 8px; height: 3em; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("📝 Corretor de Provas")
st.caption("Versao 2.1 - Com OCR via API e reconhecimento automatico")

# Verificar se a chave API está configurada
api_key = get_api_key()
if not api_key:
    st.info("Chave de API nao configurada. Usando OCR local (Tesseract) como fallback.")
else:
    st.success("Chave de API configurada com sucesso!")

# Carrega os dados salvos
historico_gabaritos = carregar_historico()

# Menu de navegação
aba1, aba2, aba3 = st.tabs(["📌 Gabaritos", "📷 Corrigir", "📊 Historico"])

# ==========================================
# ABA 1: GABARITOS
# ==========================================
with aba1:
    st.subheader("📌 Gerenciar Gabaritos")
    
    opcao_gabarito = st.radio(
        "Como deseja criar o gabarito?",
        ["✏️ Digitar manualmente", "📋 Colar texto", "📂 Importar CSV"],
        horizontal=True
    )
    
    if opcao_gabarito == "✏️ Digitar manualmente":
        with st.form("form_novo_gabarito"):
            nome_prova = st.text_input("Nome da Avaliacao", placeholder="Ex: Prova 1 - Biologia")
            num_questoes = st.number_input("Quantidade de Questoes", min_value=1, max_value=50, value=13)

            st.markdown("---")
            st.write("Selecione a alternativa correta para cada questao:")

            respostas_cadastradas = {}
            alternativas = ["A", "B", "C", "D", "E"]

            cols = st.columns(4)
            for i in range(1, int(num_questoes) + 1):
                col_atual = cols[(i - 1) % 4]
                with col_atual:
                    respostas_cadastradas[str(i)] = st.selectbox(f"Q{i}", alternativas, key=f"cad_q_{i}")

            btn_salvar = st.form_submit_button("💾 Salvar Gabarito")

            if btn_salvar:
                if not nome_prova.strip():
                    st.error("Por favor, informe o nome da avaliacao.")
                elif nome_prova in historico_gabaritos:
                    st.warning(f"Já existe um gabarito com o nome '{nome_prova}'. Deseja sobrescrever?")
                    if st.button("Sobrescrever"):
                        historico_gabaritos[nome_prova] = respostas_cadastradas
                        if salvar_historico(historico_gabaritos):
                            st.success(f"Gabarito '{nome_prova}' atualizado com sucesso!")
                else:
                    historico_gabaritos[nome_prova] = respostas_cadastradas
                    if salvar_historico(historico_gabaritos):
                        st.success(f"Gabarito '{nome_prova}' salvo com sucesso!")
    
    elif opcao_gabarito == "📋 Colar texto":
        st.info("Cole o gabarito no formato: Numero seguido de letra (ex: 1A, 2B, 3C...)")
        texto_gabarito = st.text_area("Cole aqui o gabarito", placeholder="1A\n2B\n3C\n4D\n5E", height=150)
        
        if texto_gabarito:
            nome_prova = st.text_input("Nome da Avaliacao", placeholder="Ex: Prova 1 - Biologia")
            if st.button("📥 Importar Gabarito"):
                if not nome_prova.strip():
                    st.error("Por favor, informe o nome da avaliacao.")
                else:
                    respostas_importadas = extrair_respostas_do_texto(texto_gabarito)
                    if respostas_importadas:
                        historico_gabaritos[nome_prova] = respostas_importadas
                        if salvar_historico(historico_gabaritos):
                            st.success(f"Gabarito '{nome_prova}' importado com {len(respostas_importadas)} questoes!")
                    else:
                        st.error("Nao foi possivel identificar as respostas.")
    
    elif opcao_gabarito == "📂 Importar CSV":
        st.info("Importe um arquivo CSV com as colunas: Questao,Resposta")
        arquivo_csv = st.file_uploader("Selecione o arquivo CSV", type=['csv'])
        
        if arquivo_csv:
            try:
                df = pd.read_csv(arquivo_csv)
                if 'Questão' in df.columns and 'Resposta' in df.columns:
                    respostas_importadas = {}
                    for _, row in df.iterrows():
                        respostas_importadas[str(row['Questão'])] = row['Resposta'].upper()
                    
                    nome_prova = st.text_input("Nome da Avaliacao", placeholder="Ex: Prova 1 - Biologia")
                    if st.button("📥 Importar CSV"):
                        if not nome_prova.strip():
                            st.error("Por favor, informe o nome da avaliacao.")
                        else:
                            historico_gabaritos[nome_prova] = respostas_importadas
                            if salvar_historico(historico_gabaritos):
                                st.success(f"Gabarito '{nome_prova}' importado com {len(respostas_importadas)} questoes!")
                else:
                    st.error("O CSV deve ter as colunas: 'Questão' e 'Resposta'")
            except Exception as e:
                st.error(f"Erro ao ler o arquivo: {str(e)}")

    st.markdown("---")
    st.subheader("📂 Gabaritos Salvos")
    
    if historico_gabaritos:
        gabaritos_ordenados = sorted(historico_gabaritos.items())
        for nome, gabarito in gabaritos_ordenados:
            with st.expander(f"📄 {nome} ({len(gabarito)} questoes)"):
                df_gab = pd.DataFrame(list(gabarito.items()), columns=["Questao", "Resposta Correta"])
                st.dataframe(df_gab, use_container_width=True, hide_index=True)
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"📋 Copiar", key=f"copy_{nome}"):
                        texto = "\n".join([f"{k}{v}" for k, v in gabarito.items()])
                        st.code(texto, language="text")
                with col2:
                    if st.button(f"🗑️ Excluir", key=f"del_{nome}"):
                        del historico_gabaritos[nome]
                        if salvar_historico(historico_gabaritos):
                            st.success(f"Gabarito '{nome}' excluido!")
                            st.rerun()
    else:
        st.info("Nenhum gabarito cadastrado.")

# ==========================================
# ABA 2: CORREÇÃO
# ==========================================
with aba2:
    st.subheader("📷 Corrigir Prova")
    
    if not historico_gabaritos:
        st.warning("Cadastre um gabarito na aba 'Gabaritos' antes de corrigir uma prova.")
    else:
        prova_escolhida = st.selectbox("📚 Selecione o Gabarito", list(historico_gabaritos.keys()))
        gabarito_oficial = historico_gabaritos[prova_escolhida]

        metodo_entrada = st.radio(
            "Como deseja inserir as respostas?",
            ["📷 Foto (OCR)", "⌨️ Digitar manualmente", "📋 Colar texto"],
            horizontal=True
        )
        
        if metodo_entrada == "📷 Foto (OCR)":
            if not api_key:
                st.info("Usando OCR local (Tesseract) pois a chave API nao esta configurada.")
            
            st.write("**Tire uma foto da folha de respostas:**")
            foto_aluno = st.camera_input("📸 Capturar Folha")
            
            if foto_aluno is not None:
                st.success("Foto capturada!")
                st.image(foto_aluno, caption="Foto enviada", use_container_width=True)
                
                with st.spinner("Processando imagem..."):
                    imagem = Image.open(foto_aluno)
                    respostas_extraidas = processar_imagem_para_respostas(imagem)
                
                if not respostas_extraidas:
                    st.warning("Nao foi possivel identificar respostas automaticamente.")
                    if st.button("✏️ Inserir manualmente"):
                        st.session_state['modo_manual'] = True
                else:
                    df_respostas = pd.DataFrame(
                        list(respostas_extraidas.items()), 
                        columns=["Questao", "Resposta do Aluno"]
                    )
                    st.success(f"Encontradas {len(respostas_extraidas)} respostas!")
                    st.dataframe(df_respostas, use_container_width=True, hide_index=True)
                    
                    if st.button("📊 Corrigir Prova", type="primary"):
                        calcular_correcao(respostas_extraidas, gabarito_oficial, prova_escolhida)
        
        elif metodo_entrada == "⌨️ Digitar manualmente":
            respostas_aluno = {}
            st.write("**Insira as respostas do aluno:**")
            
            cols_manual = st.columns(4)
            for i, resp_correta in gabarito_oficial.items():
                col_idx = (int(i) - 1) % 4
                with cols_manual[col_idx]:
                    respostas_aluno[i] = st.selectbox(
                        f"Q{i}", ["-", "A", "B", "C", "D", "E"],
                        key=f"manual_q_{i}",
                        help=f"Gabarito: {resp_correta}"
                    )
            
            if st.button("📊 Corrigir Prova", type="primary"):
                calcular_correcao(respostas_aluno, gabarito_oficial, prova_escolhida)
        
        elif metodo_entrada == "📋 Colar texto":
            st.write("**Cole as respostas do aluno:**")
            texto_aluno = st.text_area("Respostas", placeholder="1A\n2B\n3C\n4D\n5E", height=100)
            
            if texto_aluno:
                respostas_aluno = extrair_respostas_do_texto(texto_aluno)
                if respostas_aluno:
                    st.success(f"Identificadas {len(respostas_aluno)} respostas!")
                    df_resp = pd.DataFrame(list(respostas_aluno.items()), columns=["Questao", "Resposta"])
                    st.dataframe(df_resp, use_container_width=True, hide_index=True)
                    
                    if st.button("📊 Corrigir Prova", type="primary"):
                        calcular_correcao(respostas_aluno, gabarito_oficial, prova_escolhida)
                else:
                    st.warning("Nao foi possivel identificar as respostas.")

# ==========================================
# ABA 3: HISTÓRICO
# ==========================================
with aba3:
    st.subheader("📊 Historico de Correcoes")
    
    if 'historico_correcoes' in st.session_state and st.session_state.historico_correcoes:
        st.info(f"Total de correcoes: {len(st.session_state.historico_correcoes)}")
        
        if st.button("🗑️ Limpar Historico"):
            st.session_state.historico_correcoes = []
            st.success("Historico limpo!")
            st.rerun()
        
        for correcao in reversed(st.session_state.historico_correcoes):
            with st.expander(f"📝 {correcao.get('prova', 'Prova')} - {correcao.get('data', 'Data')}"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Nota", f"{correcao.get('nota', 0):.1f}%")
                with col2:
                    st.metric("Acertos", f"{correcao.get('acertos', 0)}/{correcao.get('total', 0)}")
                with col3:
                    st.metric("Em branco", correcao.get('nao_respondidas', 0))
                
                if 'detalhes' in correcao:
                    df_detalhes = pd.DataFrame(correcao['detalhes'])
                    st.dataframe(df_detalhes, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma correcao realizada ainda.")

st.markdown("---")
st.caption("📝 Corretor de Provas v2.1 | Desenvolvido com ❤️ usando Streamlit")
