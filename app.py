import streamlit as st
import pandas as pd
import plotly.express as px

# ==========================================================
# 1. FUNÇÕES DE LEITURA DE DADOS
# ==========================================================

@st.cache_data
def load_data_coordenadores(path_excel: str, sheet_name: str = "Planilha1"):
    """
    Lê a planilha de alocação de diretores (coordenadores locais).
    Esse arquivo contém info de quem TEM / NÃO TEM coordenador.
    """
    df = pd.read_excel(path_excel, sheet_name=sheet_name)

    # primeira linha são os nomes de coluna
    df.columns = df.iloc[0]
    df = df.drop(0).reset_index(drop=True)

    # padroniza nomes
    df = df.rename(
        columns={
            "GRE": "GRE",
            "INEP": "INEP",
            "ESCOLA": "ESCOLA",
            "REDE": "REDE",
            "POLO": "POLO",
            "NOME DO COORDENADOR": "COORDENADOR",
            "COORDENADOR": "COORDENADOR",  # fallback
        }
    )

    # cria flag TEM_COORDENADOR
    df["TEM_COORDENADOR"] = ~df["COORDENADOR"].fillna("").str.strip().str.lower().eq("sem informação")

    # status amigável
    df["STATUS_COORDENADOR"] = df["TEM_COORDENADOR"].map(
        {True: "Com Coordenador", False: "Sem Coordenador"}
    )

    return df


@st.cache_data
def load_data_totais(path_excel: str):
    """
    Lê a planilha de totais estruturais (todas as escolas / polos / GREs / turmas).
    Essa base define o denominador oficial.
    """
    df = pd.read_excel(path_excel)
    # normaliza cabeçalhos
    df.columns = df.columns.str.strip().str.upper()

    # garantimos nomes padronizados esperados: GRE, POLO, ESCOLA
    # se coluna ESCOLA vier com outro nome, podemos adaptar aqui no futuro
    return df


# ==========================================================
# 2. FUNÇÕES AUXILIARES DE AGREGAÇÃO / CÁLCULO
# ==========================================================

def calcular_percentual_conclusao_diretores(df_coord, df_total):
    """
    % de conclusão geral da alocação de diretores:
    escolas (ou registros) que têm coordenador / total de escolas na base total.
    Aqui vamos trabalhar por ESCOLA única.
    """
    total_escolas = df_total["ESCOLA"].nunique()
    escolas_com_coord = (
        df_coord[df_coord["TEM_COORDENADOR"]]["ESCOLA"].nunique()
    )
    if total_escolas == 0:
        return 0.0
    return (escolas_com_coord / total_escolas) * 100.0


def agg_por_gre(df_coord, df_total):
    """
    Para cada GRE:
    - total de ESCOLAS da base total
    - ESCOLAS com coordenador na base coord
    - % = com_coord / total
    """
    gre_totais = (
        df_total.groupby("GRE")["ESCOLA"]
        .nunique()
        .rename("total_escolas")
        .reset_index()
    )

    gre_com_coord = (
        df_coord[df_coord["TEM_COORDENADOR"]]
        .groupby("GRE")["ESCOLA"]
        .nunique()
        .rename("escolas_com_coord")
        .reset_index()
    )

    resumo = pd.merge(gre_totais, gre_com_coord, on="GRE", how="left").fillna(0)
    resumo["perc_com_coord"] = (
        resumo["escolas_com_coord"] / resumo["total_escolas"] * 100
    ).fillna(0)

    # ordenar por % desc (para gráfico e tabela)
    resumo = resumo.sort_values(by="perc_com_coord", ascending=False).reset_index(drop=True)
    return resumo


def agg_por_polo(df_coord, df_total, gre):
    """
    Dentro de uma GRE específica:
    - total de ESCOLAS por Polo (base total)
    - ESCOLAS com coordenador por Polo (base coord)
    - % = com_coord / total
    """
    total_polos = (
        df_total[df_total["GRE"] == gre]
        .groupby("POLO")["ESCOLA"]
        .nunique()
        .rename("total_escolas")
        .reset_index()
    )

    polos_com_coord = (
        df_coord[(df_coord["GRE"] == gre) & (df_coord["TEM_COORDENADOR"])]
        .groupby("POLO")["ESCOLA"]
        .nunique()
        .rename("escolas_com_coord")
        .reset_index()
    )

    resumo = pd.merge(total_polos, polos_com_coord, on="POLO", how="left").fillna(0)
    resumo["perc_com_coord"] = (
        resumo["escolas_com_coord"] / resumo["total_escolas"] * 100
    ).fillna(0)

    # manter ordem desc como na tabela anterior
    resumo = resumo.sort_values(by="perc_com_coord", ascending=False).reset_index(drop=True)
    return resumo


def resumo_status_polo(df_coord, df_total, gre, polo):
    """
    Para um Polo específico:
    - contamos registros daquele Polo na base total (todas as ocorrências)
    - dentro desse polo, contamos quantos registros têm coordenador vs não têm
      (usando a base coord)
    OBS: Aqui vamos considerar REGISTROS (linhas), não escolas únicas.
    """

    # total de registros desse polo na base total
    total_registros_polo = df_total[
        (df_total["GRE"] == gre) & (df_total["POLO"] == polo)
    ].copy()

    # marca se tem coordenador olhando df_coord (por escola)
    # estratégia: mapear escola -> tem_coordenador
    mapa_coord = (
        df_coord.groupby("ESCOLA")["TEM_COORDENADOR"]
        .max()  # se qualquer linha daquela escola tem coordenador = True
        .to_dict()
    )

    total_registros_polo["TEM_COORDENADOR"] = total_registros_polo["ESCOLA"].map(mapa_coord).fillna(False)
    total_registros_polo["STATUS_COORDENADOR"] = total_registros_polo["TEM_COORDENADOR"].map(
        {True: "Com Coordenador", False: "Sem Coordenador"}
    )

    resumo = (
        total_registros_polo.groupby("STATUS_COORDENADOR")
        .size()
        .rename("qtd_registros")
        .reset_index()
    )

    total = resumo["qtd_registros"].sum()
    resumo["percentual"] = (resumo["qtd_registros"] / total * 100).fillna(0)

    return resumo, total_registros_polo


def detalhe_escolas(df_coord, df_total, gre, polo):
    """
    Monta a tabela final para exibição:
    GRE | Polo | Escola | INEP | Coordenador | Status
    Usamos df_total como base de linhas (registros),
    mas enriquecemos com info de coordenador que vem de df_coord.
    """
    registros = df_total[
        (df_total["GRE"] == gre) & (df_total["POLO"] == polo)
    ].copy()

    # mapa auxiliar: para cada escola -> coordenador + status
    aux = (
        df_coord.groupby("ESCOLA")
        .agg({
            "INEP": "first",
            "COORDENADOR": "first",
            "TEM_COORDENADOR": "max",
            "STATUS_COORDENADOR": "first"
        })
        .reset_index()
    )

    registros = registros.merge(
        aux,
        how="left",
        left_on="ESCOLA",
        right_on="ESCOLA"
    )

    # Garantir colunas esperadas. Se não houver INEP na base coord, fica NaN
    registros["STATUS_COORDENADOR"] = registros["STATUS_COORDENADOR"].fillna("Sem Coordenador")
    registros["COORDENADOR"] = registros["COORDENADOR"].fillna("Sem informação")

    # Seleção de colunas finais (algumas podem não existir em df_total original, ex: INEP)
    colunas_finais = []
    if "GRE" in registros.columns: colunas_finais.append("GRE")
    if "POLO" in registros.columns: colunas_finais.append("POLO")
    colunas_finais += ["ESCOLA"]
    if "INEP" in registros.columns: colunas_finais.append("INEP")
    colunas_finais += ["COORDENADOR", "STATUS_COORDENADOR"]

    tabela = registros[colunas_finais].copy()

    return tabela


# ==========================================================
# 3. COMPONENTE DE RELATÓRIO "ALOCAÇÃO DE DIRETORES"
# ==========================================================

def mostrar_relatorio_alocacao_diretores(df_coord, df_total):
    # ------------------------------------------------------
    # BLOCO 1 - % Por GRE
    # ------------------------------------------------------
    st.header("1. % Por GRE de Coordenadores Alocados")

    resumo_gre = agg_por_gre(df_coord, df_total)

    col1, col2 = st.columns([2, 1], vertical_alignment="top")

    with col1:
        st.subheader("% de Registros com Coordenador por GRE")
        fig_gre = px.bar(
            resumo_gre,
            x="GRE",
            y="perc_com_coord",
            text="perc_com_coord",
            hover_data={
                "total_escolas": True,
                "escolas_com_coord": True,
                "perc_com_coord": ':.2f'
            },
            labels={
                "GRE": "GRE",
                "perc_com_coord": "% com Coordenador"
            },
            title="% de Registros com Coordenador por GRE"
        )
        fig_gre.update_traces(
            texttemplate="%{text:.1f}%",
            textposition="outside",
            marker_color="#1f77b4"
        )
        fig_gre.update_layout(
            xaxis_title="",
            yaxis_title="% com Coordenador",
            plot_bgcolor="white",
            paper_bgcolor="white"
        )
        st.plotly_chart(fig_gre, use_container_width=True)

    with col2:
        st.subheader("Tabela - GRE")
        tabela_gre = resumo_gre.copy()
        tabela_gre["perc_com_coord"] = tabela_gre["perc_com_coord"].round(1).astype(str) + "%"
        st.dataframe(
            tabela_gre.rename(
                columns={
                    "GRE": "GRE",
                    "total_escolas": "Total Registros",
                    "escolas_com_coord": "Com Coord.",
                    "perc_com_coord": "% Com Coord."
                }
            ),
            hide_index=True,
            use_container_width=True
        )

    st.markdown("— Selecione abaixo uma GRE para detalhar por Polo:\n")

    gre_escolhida = st.selectbox(
        "Escolha a GRE",
        options=list(resumo_gre["GRE"]),
        index=0
    )

    # ------------------------------------------------------
    # BLOCO 2 - Por Polo (dentro da GRE selecionada)
    # ------------------------------------------------------
    st.header(f"2. Detalhamento por Polo da {gre_escolhida}")

    resumo_polo = agg_por_polo(df_coord, df_total, gre_escolhida)

    col3, col4 = st.columns([2, 1], vertical_alignment="top")

    with col3:
        st.subheader(f"% de Registros com Coordenador por Polo ({gre_escolhida} GRE)")
        fig_polo = px.bar(
            resumo_polo,
            x="POLO",
            y="perc_com_coord",
            hover_data={
                "total_escolas": True,
                "escolas_com_coord": True,
                "perc_com_coord": ':.2f'
            },
            labels={
                "POLO": "Polo",
                "perc_com_coord": "% com Coordenador"
            },
            title=f"% de Registros com Coordenador por Polo ({gre_escolhida} GRE)"
        )
        fig_polo.update_traces(
            marker_color="#1f77b4"
        )
        fig_polo.update_layout(
            xaxis_title="",
            yaxis_title="% com Coordenador",
            plot_bgcolor="white",
            paper_bgcolor="white"
        )
        st.plotly_chart(fig_polo, use_container_width=True)

    with col4:
        st.subheader("Tabela - Polos da GRE")
        tabela_polo = resumo_polo.copy()
        tabela_polo["perc_com_coord"] = tabela_polo["perc_com_coord"].round(1).astype(str) + "%"
        st.dataframe(
            tabela_polo.rename(
                columns={
                    "POLO": "Polo",
                    "total_escolas": "Total Registros",
                    "escolas_com_coord": "Com Coord.",
                    "perc_com_coord": "% Com Coord."
                }
            ),
            hide_index=True,
            use_container_width=True
        )

    st.markdown("— Selecione abaixo um Polo dessa GRE para ver as escolas:\n")

    polo_escolhido = st.selectbox(
        "Escolha o Polo",
        options=list(resumo_polo["POLO"]),
        index=0
    )

    # ------------------------------------------------------
    # BLOCO 3 - Registros do Polo selecionado
    # ------------------------------------------------------
    st.header(f"3. Registros do Polo {polo_escolhido} na {gre_escolhida} GRE")

    # resumo_status_polo retorna:
    #   - df resumo com contagem por status
    #   - df detalhado de registros daquele polo
    resumo_status, registros_do_polo = resumo_status_polo(
        df_coord, df_total, gre_escolhida, polo_escolhido
    )

    col5, col6 = st.columns([2, 1], vertical_alignment="top")

    with col5:
        st.subheader(f"Distribuição de Coordenador no Polo {polo_escolhido}")
        fig_status = px.bar(
            resumo_status,
            x="STATUS_COORDENADOR",
            y="percentual",
            hover_data={
                "qtd_registros": True,
                "percentual": ':.2f'
            },
            labels={
                "STATUS_COORDENADOR": "Status",
                "percentual": "% de Registros"
            }
        )
        fig_status.update_traces(
            marker_color="#1f77b4",
            texttemplate="%{y:.1f}%",
            textposition="outside",
            text=resumo_status["percentual"]
        )
        fig_status.update_layout(
            xaxis_title="",
            yaxis_title="% de Registros",
            plot_bgcolor="white",
            paper_bgcolor="white"
        )
        st.plotly_chart(fig_status, use_container_width=True)

    with col6:
        st.subheader("Resumo do Polo")
        total_polo = resumo_status["qtd_registros"].sum()
        com_coord = resumo_status.loc[
            resumo_status["STATUS_COORDENADOR"] == "Com Coordenador", "qtd_registros"
        ].sum()
        sem_coord = total_polo - com_coord

        st.metric("Total de Registros no Polo", int(total_polo))
        st.metric("Com Coordenador", int(com_coord))
        st.metric("Sem Coordenador", int(sem_coord))

    # tabela final detalhada
    st.subheader("Tabela de Registros (Com e Sem Coordenador)")
    tabela_final = detalhe_escolas(df_coord, df_total, gre_escolhida, polo_escolhido)

    st.dataframe(
        tabela_final.rename(
            columns={
                "GRE": "GRE",
                "POLO": "Polo",
                "ESCOLA": "Escola",
                "INEP": "INEP",
                "COORDENADOR": "Coordenador",
                "STATUS_COORDENADOR": "Status"
            }
        ),
        hide_index=True,
        use_container_width=True,
        height=400
    )


# ==========================================================
# 4. RELATÓRIO FUTURO / PLACEHOLDER
# ==========================================================

def mostrar_relatorio_aplicadores():
    st.header("🚧 Alocação de Aplicadores")
    st.info("Relatório em desenvolvimento. Base de dados ainda não adicionada.")
    st.progress(0)


# ==========================================================
# 5. APP PRINCIPAL / SIDEBAR
# ==========================================================

def main():
    st.set_page_config(page_title="Dashboard de Alocações", layout="wide")

    # =======================
    # SIDEBAR
    # =======================
    st.sidebar.title("📊 Relatórios de Alocação")
    st.sidebar.markdown("---")

    # caminhos dos arquivos
    base_coord = st.sidebar.text_input(
        "📄 Base de Diretores (Coordenadores):",
        value="Relatório dos Coordenador de Polo - Dir Escolas.xlsx"
    )
    base_total = st.sidebar.text_input(
        "🗂️ Base de Totais Gerais:",
        value="GRE_Polo_Turma_Escola.xlsx"
    )

    # carrega bases
    df_coord = load_data_coordenadores(base_coord)
    df_total = load_data_totais(base_total)

    # progresso de conclusão de Diretores
    perc_conclusao_diretores = calcular_percentual_conclusao_diretores(df_coord, df_total)

    # bloco Alocação de Diretores
    st.sidebar.subheader("➡️ Alocação de Diretores")
    st.sidebar.progress(perc_conclusao_diretores / 100.0)
    st.sidebar.markdown(f"**{perc_conclusao_diretores:.1f}% concluído**")
    st.sidebar.caption(f"(base: {base_coord})")

    # bloco Alocação de Aplicadores (placeholder)
    st.sidebar.subheader("➡️ Alocação de Aplicadores")
    st.sidebar.progress(0.0)
    st.sidebar.markdown("**0% concluído**")
    st.sidebar.caption("(base: será adicionada futuramente)")

    st.sidebar.markdown("---")
    st.sidebar.subheader("🗂️ Configuração de Dados")
    st.sidebar.caption(f"Base de Totais: {base_total}")

    st.sidebar.markdown("---")
    relatorio_ativo = st.sidebar.radio(
        "Selecione o relatório:",
        ["Alocação de Diretores", "Alocação de Aplicadores"]
    )

    # =======================
    # CONTEÚDO PRINCIPAL
    # =======================
    if relatorio_ativo == "Alocação de Diretores":
        mostrar_relatorio_alocacao_diretores(df_coord, df_total)
    else:
        mostrar_relatorio_aplicadores()


# ==========================================================
# 6. START
# ==========================================================

if __name__ == "__main__":
    main()
