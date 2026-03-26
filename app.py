import streamlit as st
import pandas as pd
import pydeck as pdk
import plotly.graph_objects as go
import os

st.set_page_config(layout="wide", page_title="Global Intelligence Platform")

# ── Dark mode CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp                            { background-color: #0e1117 !important; }
    section[data-testid="stSidebar"]  { background-color: #161b22 !important; }
    .stApp *, [data-testid="stSidebar"] * { color: #fafafa !important; }
    div[data-baseweb="select"] > div,
    div[data-baseweb="select"] > div > div,
    [data-baseweb="base-input"],
    [data-baseweb="input"],
    input[type="number"]              { background-color: #1c2128 !important; color: #fafafa !important; border-color: #30363d !important; }
    [data-baseweb="popover"] *        { background-color: #1c2128 !important; color: #fafafa !important; }
    hr                                { border-color: #30363d !important; }
    .stToggle span                    { background-color: #c0392b !important; }
    .stDataFrame                      { background-color: #161b22 !important; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
PILLARS = [
    'authority', 'enforcement_capacity', 'information_control',
    'institutional_capacity', 'legitimacy', 'resource_concentration'
]
PILLAR_LABELS = {p: p.replace('_', ' ').title() for p in PILLARS}
PILLAR_ABBREV = {
    'authority':              'A',
    'enforcement_capacity':   'E',
    'information_control':    'IC',
    'institutional_capacity': 'In',
    'legitimacy':             'L',
    'resource_concentration': 'R'
}
PILLAR_COLORS = {
    'authority':              '#e74c3c',
    'enforcement_capacity':   '#e67e22',
    'information_control':    '#f1c40f',
    'institutional_capacity': '#2ecc71',
    'legitimacy':             '#3498db',
    'resource_concentration': '#9b59b6'
}
PHASE_COLORS = {
    'latent':   '#888888',
    'build':    '#e67e22',
    'active':   '#c0392b',
    'cooling':  '#f1c40f',
    'recovery': '#2ecc71'
}
EVENT_TYPE_COLORS = [
    '#5b9bd5', '#ed7d31', '#a5a5a5', '#ffc000',
    '#4472c4', '#70ad47', '#9b59b6', '#1abc9c',
    '#c0392b', '#f39c12', '#16a085', '#8e44ad',
]
LABEL_TIERS = [
    (50_000_000, None,       8, 'rgba(255,255,255,0.85)'),
    ( 8_000_000, 50_000_000, 8, 'rgba(255,255,255,0.85)'),
    (        0,  8_000_000,  8, 'rgba(255,255,255,0.85)'),
]
STRESS_COLORSCALE = [
    [0.000, '#628141'], [0.333, '#628141'],
    [0.333, '#E67E22'], [0.667, '#E67E22'],
    [0.667, '#750E21'], [1.000, '#750E21'],
]

def dark_layout(**kwargs):
    base = dict(
        paper_bgcolor='#0e1117', plot_bgcolor='#161b22',
        font=dict(color='#fafafa', family='Calibri'),
        xaxis=dict(gridcolor='#2a2a2a', zerolinecolor='#30363d', color='#fafafa',
                   title_font=dict(color='#fafafa')),
        yaxis=dict(gridcolor='#2a2a2a', zerolinecolor='#30363d', color='#fafafa',
                   title_font=dict(color='#fafafa')),
        legend=dict(bgcolor='#161b22', bordercolor='#30363d', font=dict(color='#fafafa')),
        hoverlabel=dict(bgcolor='#1c2128', font=dict(color='#fafafa', family='Calibri')),
    )
    base.update(kwargs)
    return base

TOOLTIP_STYLE = {
    "backgroundColor": "#1c2128", "color": "#fafafa",
    "fontFamily": "Calibri", "padding": "8px", "border": "1px solid #30363d"
}

# ── Session state ──────────────────────────────────────────────────────────────
_TAB_LABELS = ["Global Stress Map", "Country Analysis", "Country Comparison"]

_SS_DEFAULTS = {
    '_last_map_click':   None,
    '_drill_country':    None,
    '_pending_nav':      None,    # staged tab label for programmatic navigation
}
for _k, _v in _SS_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Transfer staged navigation BEFORE any widget is instantiated
if st.session_state['_pending_nav'] is not None:
    st.session_state['_tab_nav'] = st.session_state['_pending_nav']
    st.session_state['_pending_nav'] = None

# Transfer staged drill-country BEFORE any widget is instantiated
if st.session_state.get('_drill_country'):
    st.session_state['country_select'] = st.session_state['_drill_country']
    st.session_state['_drill_country'] = None

# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "Data")
    stress = pd.read_csv(os.path.join(data_dir, "stress_layer.csv"))
    panel  = pd.read_csv(os.path.join(data_dir, "full_country_panel.csv"))
    edges  = pd.read_csv(os.path.join(data_dir, "network_edges.csv"))
    refs   = pd.read_csv(os.path.join(data_dir, "country_reference.csv"))
    refs['population_hint'] = pd.to_numeric(refs['population_hint'], errors='coerce').fillna(0)
    edges = edges.merge(refs[['iso3', 'latitude', 'longitude']],
                        left_on='source_iso3', right_on='iso3', how='left')
    edges = edges.rename(columns={'latitude': 'source_lat', 'longitude': 'source_lon'}).drop(columns=['iso3'])
    edges = edges.merge(refs[['iso3', 'latitude', 'longitude']],
                        left_on='target_iso3', right_on='iso3', how='left')
    edges = edges.rename(columns={'latitude': 'target_lat', 'longitude': 'target_lon'}).drop(columns=['iso3'])
    edges = edges.dropna(subset=['source_lat', 'source_lon', 'target_lat', 'target_lon'])
    return stress, panel, edges, refs

stress_df, panel_df, edges_df, refs_df = load_data()

# ── Precomputed lookups ───────────────────────────────────────────────────────
ALL_COUNTRIES = sorted(stress_df['country'].unique().tolist())
YEAR_MIN = int(stress_df['year'].min())
YEAR_MAX = int(stress_df['year'].max())
ALL_YEARS = sorted(stress_df['year'].unique())

# ── Page navigation (fully bidirectional — no JS hacks needed) ────────────────
selected_tab = st.radio(
    "Navigation", _TAB_LABELS,
    horizontal=True, key='_tab_nav',
    label_visibility='collapsed'
)
active_idx = _TAB_LABELS.index(selected_tab) if selected_tab in _TAB_LABELS else 0

# ── Sidebar: show only the active tab's controls ──────────────────────────────
st.sidebar.markdown("## Global Intelligence Platform")
st.sidebar.markdown("---")

# ─── Global Stress Map controls (tab 0) ───────────────────────────────────────
if active_idx == 0:
    selected_year    = st.sidebar.slider("Year", int(min(ALL_YEARS)), int(max(ALL_YEARS)),
                                         int(max(ALL_YEARS)), key='map_year')
    regions          = ["All"] + sorted(stress_df['region'].dropna().unique().tolist())
    selected_region  = st.sidebar.selectbox("Region", regions, key='map_region')
    ev_opts          = ["All"] + sorted(stress_df['event_type_primary'].dropna().unique().tolist())
    selected_event   = st.sidebar.selectbox("Event Type", ev_opts, key='map_event')
    show_pillars     = st.sidebar.toggle("Pillar View", value=False, key='map_pillar_toggle')
    selected_pillar  = None
    if show_pillars:
        selected_pillar = st.sidebar.selectbox("Select Pillar", PILLARS,
                                               format_func=lambda x: PILLAR_LABELS[x],
                                               key='map_pillar_sel')
    show_small_labels = st.sidebar.toggle("Show country labels", value=False,
                                          key='map_small_labels')
else:
    selected_year     = st.session_state.get('map_year',   int(max(ALL_YEARS)))
    selected_region   = st.session_state.get('map_region', "All")
    selected_event    = st.session_state.get('map_event',  "All")
    show_pillars      = st.session_state.get('map_pillar_toggle', False)
    selected_pillar   = st.session_state.get('map_pillar_sel', None) if show_pillars else None
    show_small_labels = st.session_state.get('map_small_labels', False)

# ─── Country Analysis controls (tab 1) ────────────────────────────────────────
if active_idx == 1:
    selected_country = st.sidebar.selectbox("Select Country", ALL_COUNTRIES,
                                            key='country_select')
    year_range       = st.sidebar.slider("Year Range", YEAR_MIN, YEAR_MAX,
                                         (YEAR_MIN, YEAR_MAX), key='country_year')
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Network View**")
    top_n_enabled    = st.sidebar.checkbox("Limit to Top N connections", value=False,
                                           key='top_n_enabled')
    top_n = 10
    if top_n_enabled:
        top_n = st.sidebar.number_input("Top N by weight", min_value=1, max_value=100,
                                        value=10, step=1, key='top_n_val')
else:
    selected_country = st.session_state.get('country_select',
                                            ALL_COUNTRIES[0] if ALL_COUNTRIES else '')
    year_range    = st.session_state.get('country_year', (YEAR_MIN, YEAR_MAX))
    top_n_enabled = st.session_state.get('top_n_enabled', False)
    top_n         = int(st.session_state.get('top_n_val', 10))

# ─── Country Comparison controls (tab 2) ──────────────────────────────────────
if active_idx == 2:
    selected_countries = st.sidebar.multiselect("Select Countries", ALL_COUNTRIES,
                                                default=ALL_COUNTRIES[:3],
                                                key='trends_countries')
    metric_opts        = ["Stress Index"] + [PILLAR_LABELS[p] for p in PILLARS]
    selected_metrics   = st.sidebar.multiselect("Metrics", metric_opts,
                                                default=["Stress Index"],
                                                key='trends_metrics')
    t_year_range       = st.sidebar.slider("Year Range", YEAR_MIN, YEAR_MAX,
                                           (YEAR_MIN, YEAR_MAX), key='trends_year')
else:
    selected_countries = st.session_state.get('trends_countries', ALL_COUNTRIES[:3])
    selected_metrics   = st.session_state.get('trends_metrics', ["Stress Index"])
    t_year_range       = st.session_state.get('trends_year', (YEAR_MIN, YEAR_MAX))

st.sidebar.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: GLOBAL STRESS MAP
# ══════════════════════════════════════════════════════════════════════════════
if active_idx == 0:
    # Title reflects pillar view when active
    if show_pillars and selected_pillar:
        st.title(PILLAR_LABELS[selected_pillar])
    else:
        st.title("Global Stress Map")

    # Filter data
    map_data = stress_df[stress_df['year'] == selected_year].copy()
    if selected_region != "All":
        map_data = map_data[map_data['region'] == selected_region]
    if selected_event != "All":
        map_data = map_data[map_data['event_type_primary'] == selected_event]

    # Colorbar (vertical right)
    colorbar_right = dict(
        x=1.02, xanchor='left', y=0.5, yanchor='middle',
        thickness=14, len=0.6,
        tickfont=dict(color='#fafafa'), bgcolor='#161b22', bordercolor='#30363d',
    )

    if show_pillars and selected_pillar:
        pillar_year = panel_df[panel_df['year'] == selected_year][['iso3', selected_pillar]].copy()
        map_data = map_data.merge(pillar_year, on='iso3', how='left')
        z_vals = map_data[selected_pillar].fillna(0)
        fig_map = go.Figure(go.Choropleth(
            locations=map_data['iso3'], z=z_vals, text=map_data['country'],
            customdata=map_data[['stress_band', 'event_type_primary', 'confidence_band']].values,
            colorscale=[[0, '#0a2744'], [0.5, '#2471a3'], [1, '#aed6f1']],
            zmin=z_vals.min(), zmax=z_vals.max(),
            colorbar=dict(**colorbar_right,
                          tickvals=[z_vals.min(), z_vals.max()],
                          ticktext=['Low', 'High'],
                          title=dict(text=PILLAR_LABELS[selected_pillar], font=dict(color='#fafafa'))),
            hovertemplate=(
                "<b>%{text}</b><br>" + PILLAR_LABELS[selected_pillar] + ": %{z:.1f}<br>"
                "Stress Band: %{customdata[0]}<br>Event: %{customdata[1]}<br>"
                "Confidence: %{customdata[2]}<extra></extra>"),
            marker_line_color='#30363d', marker_line_width=0.5,
        ))
    else:
        band_num = {'Low': 1, 'Medium': 2, 'High': 3}
        map_data['stress_num'] = map_data['stress_band'].map(band_num).fillna(2)
        fig_map = go.Figure(go.Choropleth(
            locations=map_data['iso3'], z=map_data['stress_num'], text=map_data['country'],
            customdata=map_data[['stress_index', 'stress_band',
                                  'event_type_primary', 'event_phase', 'confidence_band']].values,
            colorscale=STRESS_COLORSCALE, zmin=1, zmax=3,
            colorbar=dict(**colorbar_right,
                          tickvals=[1.333, 2.0, 2.667], ticktext=['Low', 'Medium', 'High'],
                          title=dict(text='Stress Level', font=dict(color='#fafafa'))),
            hovertemplate=(
                "<b>%{text}</b><br>Stress Index: %{customdata[0]:.1f}<br>"
                "Band: %{customdata[1]}<br>Event: %{customdata[2]}<br>"
                "Phase: %{customdata[3]}<br>Confidence: %{customdata[4]}<extra></extra>"),
            marker_line_color='#2a2a2a', marker_line_width=0.4,
        ))

    # Tiered country labels
    label_ref = refs_df[['iso3', 'latitude', 'longitude', 'population_hint']].copy()
    label_all = map_data.merge(label_ref, on='iso3', how='left').dropna(subset=['latitude', 'longitude'])
    for min_pop, max_pop, fsize, fcolor in LABEL_TIERS:
        if not show_small_labels:
            continue
        tier = label_all[label_all['population_hint'] >= min_pop]
        if max_pop is not None:
            tier = tier[tier['population_hint'] < max_pop]
        if tier.empty:
            continue
        fig_map.add_trace(go.Scattergeo(
            lat=tier['latitude'], lon=tier['longitude'], text=tier['country'],
            mode='text', textfont=dict(size=fsize, color=fcolor),
            hoverinfo='skip', showlegend=False,
        ))

    fig_map.update_geos(
        showframe=False,
        showcoastlines=True, coastlinecolor='#444444',
        showland=True, landcolor='#1c2128',
        showocean=True, oceancolor='#0e1117',
        showcountries=True, countrycolor='#2a2a2a',
        bgcolor='#0e1117', projection_type='natural earth',
    )
    fig_map.update_layout(
        paper_bgcolor='#0e1117', geo_bgcolor='#0e1117',
        margin=dict(l=0, r=0, t=20, b=0), height=540,
        hoverlabel=dict(bgcolor='#1c2128', font=dict(color='#fafafa', family='Calibri')),
    )

    # Render — click a country to navigate to Country Analysis
    event = st.plotly_chart(fig_map, width='stretch', on_select="rerun", key="choropleth_chart")
    selection = getattr(event, 'selection', None) if event else None
    pts = getattr(selection, 'points', []) if selection else []
    if pts:
        clicked_country = pts[0].get('text', '')
        if (clicked_country
                and clicked_country in set(stress_df['country'].tolist())
                and st.session_state['_last_map_click'] != clicked_country):
            st.session_state['_last_map_click'] = clicked_country
            st.session_state['_drill_country'] = clicked_country
            st.session_state['_pending_nav']   = "Country Analysis"
            st.rerun()
    else:
        st.session_state['_last_map_click'] = None

    # Country ranking table
    st.markdown("---")
    st.subheader("Country Rankings")

    if show_pillars and selected_pillar:
        t_cols = ['country', 'region', 'stress_index', 'stress_band',
                  'event_type_primary', 'state_regime', selected_pillar, 'confidence_band']
        table_df = map_data[t_cols].copy().rename(columns={
            'country': 'Country', 'region': 'Region', 'stress_index': 'Stress Index',
            'stress_band': 'Stress Band', 'event_type_primary': 'Event Type',
            'state_regime': 'Regime', selected_pillar: PILLAR_LABELS[selected_pillar],
            'confidence_band': 'Confidence',
        })
        sort_col = PILLAR_LABELS[selected_pillar]
        fmt = {'Stress Index': '{:.1f}', PILLAR_LABELS[selected_pillar]: '{:.1f}'}
    else:
        t_cols = ['country', 'region', 'stress_index', 'stress_band',
                  'event_type_primary', 'state_regime', 'event_phase', 'confidence_band']
        table_df = map_data[t_cols].copy().rename(columns={
            'country': 'Country', 'region': 'Region', 'stress_index': 'Stress Index',
            'stress_band': 'Stress Band', 'event_type_primary': 'Event Type',
            'state_regime': 'Regime', 'event_phase': 'Phase', 'confidence_band': 'Confidence',
        })
        sort_col = 'Stress Index'
        fmt = {'Stress Index': '{:.1f}'}

    table_df = table_df.sort_values(sort_col, ascending=False).reset_index(drop=True)
    table_df.index += 1
    st.dataframe(table_df.style.format(fmt).set_properties(**{'text-align': 'right'}),
                 width='stretch', height=400)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: COUNTRY ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
elif active_idx == 1:
    st.title(f"Country Analysis — {selected_country}")

    country_stress = stress_df[
        (stress_df['country'] == selected_country) &
        (stress_df['year'] >= year_range[0]) &
        (stress_df['year'] <= year_range[1])
    ].sort_values('year')

    country_panel = panel_df[
        (panel_df['country'] == selected_country) &
        (panel_df['year'] >= year_range[0]) &
        (panel_df['year'] <= year_range[1])
    ].sort_values('year')

    iso3_match = stress_df[stress_df['country'] == selected_country]['iso3']
    country_iso3 = iso3_match.iloc[0] if len(iso3_match) > 0 else ''

    # ── Charts side by side ────────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Stress Index Over Time")
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(
            x=country_stress['year'], y=country_stress['stress_index'],
            mode='lines', name='Stress Index',
            line=dict(color='#c0392b', width=2.5, shape='spline'), hoverinfo='skip'
        ))
        unique_events = sorted(country_stress['event_type_primary'].dropna().unique().tolist())
        for i, evt in enumerate(unique_events):
            evt_data = country_stress[country_stress['event_type_primary'] == evt]
            color = EVENT_TYPE_COLORS[i % len(EVENT_TYPE_COLORS)]
            fig1.add_trace(go.Scatter(
                x=evt_data['year'], y=evt_data['stress_index'],
                mode='markers', name=evt,
                marker=dict(color=color, size=9, line=dict(color='#0e1117', width=1)),
                customdata=list(zip(
                    evt_data['event_phase'].fillna('').values,
                    evt_data['confidence_band'].fillna('').values
                )),
                hovertemplate=(f"<b>{selected_country}</b><br>"
                               "Year: %{x}<br>Stress Index: %{y:.1f}<br>"
                               f"Event: {evt}<br>Phase: %{{customdata[0]}}<br>"
                               "Confidence: %{customdata[1]}<extra></extra>")
            ))
        for _, row in country_stress[country_stress['event_signal'] > 0].iterrows():
            fig1.add_vline(x=row['year'], line_dash="dot",
                           line_color="#c0392b", line_width=1, opacity=0.4)
        fig1.update_layout(**dark_layout(
            xaxis_title="Year", yaxis_title="Stress Index", height=520,
            legend=dict(orientation='h', yanchor='bottom', y=1.02,
                        xanchor='right', x=1, bgcolor='#161b22',
                        bordercolor='#30363d', font=dict(color='#fafafa'))
        ))
        st.plotly_chart(fig1, width='stretch')

    with col_right:
        st.subheader("Pillar Performance Over Time")
        fig2 = go.Figure()
        for pillar in PILLARS:
            fig2.add_trace(go.Scatter(
                x=country_panel['year'], y=country_panel[pillar],
                mode='lines+markers', name=PILLAR_ABBREV[pillar],
                line=dict(color=PILLAR_COLORS[pillar], width=2, shape='spline'),
                marker=dict(size=5),
                hovertemplate=(f"<b>{PILLAR_LABELS[pillar]}</b><br>"
                               "Year: %{x}<br>Value: %{y:.1f}<extra></extra>")
            ))
        fig2.update_layout(**dark_layout(
            xaxis_title="Year", yaxis_title="Pillar Score", height=520,
            legend=dict(orientation='h', yanchor='bottom', y=1.02,
                        xanchor='right', x=1, bgcolor='#161b22',
                        bordercolor='#30363d', font=dict(color='#fafafa'))
        ))
        st.plotly_chart(fig2, width='stretch')

    # ── Network section ────────────────────────────────────────────────────────
    net_title_col, net_ctrl_col = st.columns([3, 2])
    with net_ctrl_col:
        network_mode = st.radio("Influence direction", ["Incoming influence", "Outgoing influence"],
                                horizontal=True, label_visibility='hidden',
                                key='network_mode')
    mode_label = "Incoming" if network_mode == "Incoming influence" else "Outgoing"
    with net_title_col:
        st.subheader(f"Relational Network — {mode_label} Influence")

    if network_mode == "Incoming influence":
        net_df = edges_df[edges_df['target_country'] == selected_country].copy()
    else:
        net_df = edges_df[edges_df['source_country'] == selected_country].copy()

    if top_n_enabled and len(net_df) > 0:
        net_df = net_df.nlargest(int(top_n), 'edge_weight')


    if net_df.empty:
        st.warning("No network connections found for this country with current filters.")
    else:
        net_df = net_df.copy()
        net_df['arc_width'] = (net_df['edge_weight'] * 60).clip(lower=1)

        edge_pairs = set(zip(net_df['source_iso3'], net_df['target_iso3']))
        def assign_height(row):
            if (row['target_iso3'], row['source_iso3']) in edge_pairs:
                return 0.6 if row['source_iso3'] < row['target_iso3'] else 1.4
            return 1.0
        net_df['arc_height'] = net_df.apply(assign_height, axis=1)

        if network_mode == "Incoming influence":
            node_lat, node_lon, node_name = 'source_lat', 'source_lon', 'source_country'
        else:
            node_lat, node_lon, node_name = 'target_lat', 'target_lon', 'target_country'

        node_df = net_df[[node_lat, node_lon, node_name]].drop_duplicates().copy()
        node_df = node_df.rename(columns={node_lat: 'lat', node_lon: 'lon', node_name: 'label'})
        node_df['color'] = [[192, 57, 43, 210]] * len(node_df)

        arc_layer = pdk.Layer(
            "ArcLayer", data=net_df, get_width="arc_width",
            get_source_position=["source_lon", "source_lat"],
            get_target_position=["target_lon", "target_lat"],
            get_tilt=0, get_height="arc_height",
            get_source_color=[255, 200, 200, 160], get_target_color=[160, 0, 0, 230],
            pickable=True, auto_highlight=True,
        )
        scatter_layer = pdk.Layer(
            "ScatterplotLayer", data=node_df, get_position=["lon", "lat"],
            get_radius=80000, get_fill_color="color",
            get_line_color=[255, 255, 255, 140], stroked=True,
            line_width_min_pixels=1, pickable=False,
        )

        ref_row = refs_df[refs_df['iso3'] == country_iso3]
        clat = float(ref_row['latitude'].iloc[0]) if len(ref_row) > 0 else 20.0
        clon = float(ref_row['longitude'].iloc[0]) if len(ref_row) > 0 else 0.0

        src_list = net_df['source_country'].tolist()
        tgt_list = net_df['target_country'].tolist()
        weights  = net_df['edge_weight'].tolist()

        src_weight = net_df.groupby('source_country')['edge_weight'].sum().sort_values(ascending=False)
        unique_src = [s for s in src_weight.index if s in set(src_list)]
        tgt_weight = net_df.groupby('target_country')['edge_weight'].sum().sort_values(ascending=False)
        unique_tgt = [t for t in tgt_weight.index if t not in set(unique_src)]

        all_nodes  = unique_src + unique_tgt
        node_index = {name: i for i, name in enumerate(all_nodes)}
        n_src, n_tgt = len(unique_src), len(unique_tgt)

        x_pos  = [0.01] * n_src + [0.99] * n_tgt
        y_pos  = [(i+1)/(n_src+1) for i in range(n_src)] + [(i+1)/(n_tgt+1) for i in range(n_tgt)]

        sankey = go.Figure(go.Sankey(
            arrangement="snap",
            node=dict(pad=15, thickness=16, label=all_nodes,
                      x=x_pos, y=y_pos,
                      color=["rgba(192,57,43,0.85)"] * n_src + ["rgba(120,30,20,0.85)"] * n_tgt,
                      line=dict(color="#30363d", width=0.5)),
            link=dict(
                source=[node_index[s] for s in src_list],
                target=[node_index[t] for t in tgt_list],
                value=weights, customdata=weights,
                hovertemplate=("<b>%{source.label}</b> → <b>%{target.label}</b>"
                               "<br>Weight: %{customdata:.4f}<extra></extra>"),
                color=["rgba(192,57,43,0.18)"] * len(weights),
            )
        ))
        shared_height = min(680, max(420, max(n_src, n_tgt) * 40 + 150))
        sankey.update_layout(
            height=shared_height, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor='#0e1117', font=dict(size=12, color='#fafafa', family='Calibri'),
        )

        map_col, flow_col = st.columns(2)
        with map_col:
            st.caption("Network Map")
            st.pydeck_chart(
                pdk.Deck(
                    layers=[arc_layer, scatter_layer],
                    initial_view_state=pdk.ViewState(
                        latitude=clat, longitude=clon, zoom=2.5, pitch=0, bearing=0),
                    tooltip={"html": "<b>{source_country}</b> → <b>{target_country}</b>"
                                     "<br/>Weight: {edge_weight}",
                             "style": TOOLTIP_STYLE},
                    map_style=pdk.map_styles.DARK,
                ),
                height=shared_height,
            )
        with flow_col:
            st.caption("Network Flow")
            st.plotly_chart(sankey, width='stretch')


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: COUNTRY COMPARISON
# ══════════════════════════════════════════════════════════════════════════════
elif active_idx == 2:
    st.title("Country Comparison")

    if not selected_countries:
        st.warning("Please select at least one country in the left panel.")
    elif not selected_metrics:
        st.warning("Please select at least one metric in the left panel.")
    else:
        for metric in selected_metrics:
            st.subheader(metric)
            fig = go.Figure()
            for country in selected_countries:
                if metric == "Stress Index":
                    cdata = stress_df[
                        (stress_df['country'] == country) &
                        (stress_df['year'] >= t_year_range[0]) &
                        (stress_df['year'] <= t_year_range[1])
                    ].sort_values('year')
                    y_vals = cdata['stress_index']
                    custom = cdata['event_type_primary'].fillna('').values
                else:
                    pillar_key = [p for p in PILLARS if PILLAR_LABELS[p] == metric][0]
                    cdata = panel_df[
                        (panel_df['country'] == country) &
                        (panel_df['year'] >= t_year_range[0]) &
                        (panel_df['year'] <= t_year_range[1])
                    ].sort_values('year')
                    cdata = cdata.merge(stress_df[['country', 'year', 'event_type_primary']],
                                        on=['country', 'year'], how='left')
                    y_vals = cdata[pillar_key]
                    custom = cdata['event_type_primary'].fillna('').values

                if len(cdata) == 0:
                    continue

                fig.add_trace(go.Scatter(
                    x=cdata['year'], y=y_vals,
                    mode='lines+markers', name=country,
                    text=[country] * len(cdata), customdata=custom,
                    hovertemplate=("<b>%{text}</b><br>Year: %{x}<br>" + metric +
                                   ": %{y:.1f}<br>Event: %{customdata}<extra></extra>"),
                    line=dict(width=2, shape='spline'), marker=dict(size=5)
                ))

            fig.update_layout(**dark_layout(
                xaxis_title="Year", yaxis_title=metric, height=420
            ))
            st.plotly_chart(fig, width='stretch')
