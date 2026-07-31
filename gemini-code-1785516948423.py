import json
import os
import pandas as pd
import streamlit as st

# Arquivo JSON local para salvar o histórico de gabaritos
DB_FILE = "gabaritos_historico.json"


def carregar_historico():
  if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
      return json.load(f)
  return {}


def salvar_historico(dados):
  with open(DB_FILE, "w", encoding="utf-8") as f:
    json.dump(dados, f, ensure_ascii=False, indent=4)


# Configuração da página otimizada para visualização mobile
st.set_page_config(
    page_title="Corretor Mobile", page_icon="📝", layout="centered"
)

# Estilização CSS simples para deixar o app com cara de aplicativo mobile moderno
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        height: 3em;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

st.title("📝 Corretor de Provas Mobile")
st.write("Crie gabaritos dinâmicos e corrija avaliações direto pelo celular.")

# Carrega os dados salvos
historico_gabaritos = carregar_historico()

# Menu de navegação por abas (ótimo para telas verticais de celular)
aba1, aba2 = st.tabs(["📌 Criar / Ver Gabaritos", "📷 Corrigir Prova"])

# ==========================================
# ABA 1: CRIAR E GERENCIAR GABARITOS
# ==========================================
with aba1:
  st.subheader("Cadastro de Novo Gabarito")

  with st.form("form_novo_gabarito"):
    nome_prova = st.text_input(
        "Nome da Avaliação (ex: Prova 1 - Biologia)",
        placeholder="Digite o identificador...",
    )
    num_questoes = st.number_input(
        "Quantidade de Questões", min_value=1, max_value=50, value=13
    )

    st.markdown("---")
    st.write("Selecione a alternativa correta para cada questão:")

    respostas_cadastradas = {}
    alternativas = ["A", "B", "C", "D", "E"]

    # Exibição compacta em colunas para facilitar o preenchimento no celular
    cols = st.columns(4)
    for i in range(1, int(num_questoes) + 1):
      col_atual = cols[(i - 1) % 4]
      with col_atual:
        respostas_cadastradas[str(i)] = st.selectbox(
            f"Q{i}", alternativas, key=f"cad_q_{i}"
        )

    btn_salvar = st.form_submit_button("Salvar Gabarito no Histórico")

    if btn_salvar:
      if not nome_prova.strip():
        st.error("Por favor, informe o nome da avaliação.")
      else:
        historico_gabaritos[nome_prova] = respostas_cadastradas
        salvar_historico(historico_gabaritos)
        st.success(f"Gabarito '{nome_prova}' salvo com sucesso!")

  st.markdown("---")
  st.subheader("📂 Histórico de Gabaritos")

  if historico_gabaritos:
    for nome, gabarito in list(historico_gabaritos.items()):
      with st.expander(f"📄 {nome} ({len(gabarito)} questões)"):
        # Mostra o gabarito em formato de lista limpa
        df_gab = pd.DataFrame(
            list(gabarito.items()), columns=["Questão", "Resposta Correta"]
        )
        st.table(df_gab)

        if st.button(f"Excluir '{nome}'", key=f"del_{nome}"):
          del historico_gabaritos[nome]
          salvar_historico(historico_gabaritos)
          st.rerun()
  else:
    st.info("Nenhum gabarito cadastrado no histórico até o momento.")

# ==========================================
# ABA 2: CORREÇÃO DE PROVAS (COM CÂMERA)
# ==========================================
with aba2:
  st.subheader("Correção de Provas")

  if not historico_gabaritos:
    st.warning("Cadastre ao menos um gabarito na aba anterior para prosseguir.")
  else:
    prova_escolhida = st.selectbox(
        "Selecione o Gabarito de Referência", list(historico_gabaritos.keys())
    )
    gabarito_oficial = historico_gabaritos[prova_escolhida]

    st.markdown("---")
    st.write(
        "**Passo 1:** Tire uma foto da prova/folha de respostas do aluno com a"
        " câmera do celular."
    )

    # Componente nativo do Streamlit otimizado para celulares (Abre a câmera diretamente)
    foto_aluno = st.camera_input("Capturar Folha de Respostas")

    if foto_aluno is not None:
      st.success("Foto capturada com sucesso!")
      st.image(foto_aluno, caption="Foto enviada", use_container_width=True)

      st.markdown("---")
      st.write(
          "**Passo 2:** Insira as respostas assinaladas pelo aluno na prova para"
          " conferência e cálculo automático da nota:"
      )

      respostas_aluno = {}
      cols_cor = st.columns(3)

      for i, resp_correta in gabarito_oficial.items():
        col_idx = (int(i) - 1) % 3
        with cols_cor[col_idx]:
          respostas_aluno[i] = st.selectbox(
              f"Resp. Aluno Q{i}",
              ["-", "A", "B", "C", "D", "E"],
              key=f"aluno_q_{i}",
          )

      if st.button("Calcular Nota Final"):
        acertos = 0
        total_questoes = len(gabarito_oficial)
        detalhes = []

        for q, gab_correto in gabarito_oficial.items():
          resp_al = respostas_aluno[q]
          status = "❌ Errado"
          if resp_al == gab_correto:
            acertos += 1
            status = "✅ Correto"

          detalhes.append({
              "Questão": f"Q{q}",
              "Gab. Oficial": gab_correto,
              "Resp. Aluno": resp_al,
              "Resultado": status,
          })

        nota_final = (acertos / total_questoes) * 100

        st.markdown("---")
        st.subheader("📊 Resultado da Correção")
        st.metric(
            label="Nota Final / Desempenho",
            value=f"{nota_final:.1f}%",
            delta=f"{acertos} acertos de {total_questoes}",
        )

        df_detalhes = pd.DataFrame(detalhes)
        st.table(df_detalhes)
