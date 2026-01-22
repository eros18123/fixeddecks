# html.py
import os

def generate_report(rows_data, totals, daily_stats, cfg, is_night, media_dir, lang, last_review_time, global_streak):
    """
    Gera o HTML completo do relatório (Lista ou Grade) baseado nos dados recebidos.
    """
    
    # Cores e Variáveis CSS
    bg_color = "#333333" if is_night else "#ffffff"
    text_color = "#ffffff" if is_night else "#000000"
    muted_color = "#aaaaaa" if is_night else "#888888"
    border_color = "#555555" if is_night else "#cccccc"
    header_bg = "#444444" if is_night else "#e0e0e0"
    progress_bg = "#444444" if is_night else "#dddddd"
    input_bg = "#222222" if is_night else "#ffffff"

    col_widths = cfg.get("col_widths", {})
    is_grid = cfg.get("is_grid_view", False)
    
    table_width_val = cfg.get("table_width", 98)
    if table_width_val is None: table_width_val = 98
    table_width_style = f"{table_width_val}%" 

    # HTML dos status diários (cabeçalho)
    label_time = lang.get("last_review_time_label", "Última rev:")
    label_streak = lang.get("global_streak_label", "{day} dias seguidos").format(day=global_streak)
    
    daily_html = f"""
    <div style="display:flex; flex-direction:column; align-items:flex-end; margin-right:15px;">
        <div style="font-size:10px; color:{muted_color}; margin-bottom:1px; font-weight:bold;">
            {label_time} {last_review_time} <span style="color:#FFD700; margin-left:5px;">🔥 {label_streak}</span>
        </div>
        <div style="display:flex; gap:8px; font-size:12px; background:rgba(127,127,127,0.2); padding:3px 8px; border-radius:4px; align-items:center;">
            <span style="color:#ff5a5a; font-weight:bold;">■ {daily_stats.get(1, 0)}</span>
            <span style="color:#ff9d5a; font-weight:bold;">■ {daily_stats.get(2, 0)}</span>
            <span style="color:#5aff5a; font-weight:bold;">■ {daily_stats.get(3, 0)}</span>
            <span style="color:#5a9dff; font-weight:bold;">■ {daily_stats.get(4, 0)}</span>
        </div>
    </div>
    """

    leech_val = cfg.get("leech_threshold", 10)
    streak_val = cfg.get("streak_threshold", 20)

    # Funções Auxiliares
    def format_time_str(total_seconds):
        if total_seconds <= 0: return "-"
        if total_seconds < 60: return f"{int(total_seconds)}s"
        elif total_seconds < 3600: return f"{int(total_seconds / 60)}m"
        else:
            hours = int(total_seconds / 3600)
            minutes = int((total_seconds % 3600) / 60)
            if minutes > 0: return f"{hours}h {minutes}m"
            return f"{hours}h"

    def get_rpg_icon(mature_count, total_cards):
        if total_cards == 0: return "🌱"
        pct = (mature_count / total_cards) * 100
        
        if pct <= 10: return "🌱"    # 0-10%
        elif pct <= 20: return "🌿"  # 11-20%
        elif pct <= 30: return "🍃"  # 21-30%
        elif pct <= 40: return "🌳"  # 31-40%
        elif pct <= 50: return "🌲"  # 41-50%
        elif pct <= 60: return "🌴"  # 51-60%
        elif pct <= 70: return "🌸"  # 61-70%
        elif pct <= 80: return "🌻"  # 71-80%
        elif pct <= 90: return "💎"  # 81-90%
        else: return "👑"            # 91-100%

    def get_global_rpg_level(total_xp):
        levels = [
            (0, lang["level_0_name"], "#a0a0a0"),
            (100, lang["level_1_name"], "#cd7f32"),
            (300, lang["level_2_name"], "#c0c0c0"),
            (600, lang["level_3_name"], "#ffd700"),
            (1000, lang["level_4_name"], "#00ced1"),
            (1500, lang["level_5_name"], "#9932cc"),
            (2500, lang["level_6_name"], "#ff4500"),
            (4000, lang["level_7_name"], "#ff00ff")
        ]

        if total_xp < 0:
            return lang["level_cursed"], "#555", 0, 0, 0, 100

        if total_xp >= 4000:
            return lang["level_7_name"], "#ff00ff", 1.0, 1.0, total_xp, "∞"

        current_idx = 0
        for i, (threshold, _, _) in enumerate(levels):
            if total_xp >= threshold:
                current_idx = i
            else:
                break
        
        floor, title, color = levels[current_idx]
        ceiling = levels[current_idx + 1][0]
        
        xp_needed_for_level = ceiling - floor
        xp_progress_in_level = total_xp - floor
        
        pct_level = xp_progress_in_level / xp_needed_for_level
        pct_global = total_xp / 4000.0
        
        return title, color, pct_level, pct_global, xp_progress_in_level, xp_needed_for_level

    # --- Global Level Bar ---
    global_xp = totals.get("xp", 0)
    lvl_title, lvl_color, lvl_pct, global_pct, lvl_curr, lvl_max = get_global_rpg_level(global_xp)
    
    lvl_pct_val = lvl_pct * 100
    global_pct_val = global_pct * 100
    
    if lvl_title == lang["level_7_name"]:
        tooltip_level = lang["max_level_reached"]
    else:
        tooltip_level = f"{lvl_curr}/{lvl_max} {lvl_title} ({lvl_pct_val:.1f}%)"
        
    tooltip_global = f"{lang['global_progress']}: {global_xp}/4000 ({global_pct_val:.1f}%)"
    
    global_level_html = f'''
    <div style="flex-grow:1; margin:0 15px; display:flex; flex-direction:column; justify-content:center; min-width: 200px;">
        <div style="display:flex; justify-content:space-between; font-size:11px; font-weight:bold; color:{lvl_color}; margin-bottom:2px;">
            <span>{lvl_title}</span>
            <span>{global_xp} XP</span>
        </div>
        
        <!-- Barra 1: Nível Atual -->
        <div title="{tooltip_level}" style="width:100%; height:5px; background:rgba(127,127,127,0.3); border-radius:3px; margin-bottom:3px; overflow:hidden; cursor:help;">
            <div style="width:{lvl_pct_val}%; height:100%; background:{lvl_color};"></div>
        </div>
        
        <!-- Barra 2: Global -->
        <div title="{tooltip_global}" style="width:100%; height:5px; background:rgba(127,127,127,0.3); border-radius:3px; overflow:hidden; cursor:help;">
            <div style="width:{global_pct_val}%; height:100%; background:linear-gradient(90deg, #4da6ff, #aa88ff);"></div>
        </div>
    </div>
    '''

    # --- RENDERIZAÇÃO: MODO GRADE (GRID) ---
    def render_grid_view():
        grid_html = '<div class="grid-container">'
        
        col_order = cfg.get("column_order", [])

        for row in rows_data:
            did = row.get("did")
            name = row["name"]
            depth = row["depth"]
            new, lrn, due = row["counts"]
            
            # Stats
            maturity, retention, total_cards, tomorrow, done_today, speed, ease, leeches, mature_count_int, avg_time, _, total_stars, _, ease_counts, maturity_pct = row["stats"]
            
            # RPG Stats
            hp, xp, hp_pct = row.get("rpg", (100, 0, 100))
            xp_display = f'<span style="font-size:10px; color:#FFD700; font-weight:bold;">+{xp} XP</span>' if xp >= 0 else f'<span style="font-size:10px; color:#ff5a5a; font-weight:bold;">{xp} XP</span>'
            
            deck_goal = row["goal"]
            row_bg = row["bg_color"]
            recursive_seconds = row.get("recursive_seconds", 0)
            
            # Capa
            cover_file = cfg.get("deck_covers", {}).get(str(did)) if did else None
            cover_html = ""
            text_shadow_style = ""
            
            bg_style = f'background-color:{row_bg};' if row_bg else 'background-color:var(--input-bg);'
            
            if cover_file:
                full_path = os.path.join(media_dir, cover_file)
                full_path = full_path.replace("\\", "/")
                cover_html = f'<img src="{full_path}" class="grid-cover"><div class="grid-overlay"></div>'
                text_shadow_style = 'text-shadow: 0 1px 3px rgba(0,0,0,0.9); color: #fff;'
                bg_style = 'background-color: #000;'

            border_colors = ["#4da6ff", "#ff9999", "#5aff5a", "#FFD700", "#aa88ff"]
            border_color_depth = border_colors[depth % 5]
            depth_style = f'border-left: 3px solid {border_color_depth};' if depth > 0 else ''

            rpg_icon = get_rpg_icon(mature_count_int, total_cards)

            # Barra de Progresso
            progress_html = ""
            if cfg.get("show_progress", True):
                remaining = new + lrn + due
                daily_total = done_today + remaining
                daily_pct = 0
                if daily_total > 0: daily_pct = (done_today / daily_total) * 100
                elif done_today > 0: daily_pct = 100
                
                is_goal_met = done_today >= deck_goal and deck_goal > 0
                if is_goal_met: bar_color = "#FFD700"
                elif daily_pct < 50: bar_color = "#ff5a5a"
                elif daily_pct < 100: bar_color = "#4da6ff"
                else: bar_color = "#5aff5a"
                
                progress_html = f'''
                <div style="width: 100%; height: 4px; background: rgba(255,255,255,0.3); margin: 4px 0; border-radius: 2px; overflow: hidden; position: relative; z-index: 2;">
                    <div style="width: {daily_pct}%; height: 100%; background: {bar_color};"></div>
                </div>
                '''

            time_str = format_time_str(recursive_seconds)
            
            leech_style = f'color:{"#ff5a5a" if leeches > 0 else muted_color}'
            if cover_file and leeches == 0: leech_style = "color: rgba(255,255,255,0.7);"
            
            tom_style = f'color:{"#ff9999" if tomorrow > 50 else muted_color}'
            if cover_file and tomorrow <= 50: tom_style = "color: rgba(255,255,255,0.7);"

            data_map = {
                "show_time": ("⏱️", time_str),
                "show_avg_time": ("s/card", avg_time),
                "show_speed": ("🚀", speed),
                "show_goal": ("🎯", f"{deck_goal}"),
                "show_retention": ("% Hj", retention),
                "show_ease": ("⚖️", ease),
                "show_leeches": ("🩸", f'<span style="{leech_style}">{leeches}</span>'),
                "show_tomorrow": ("🔮", f'<span style="{tom_style}">{tomorrow}</span>'),
                "show_total": (lang["total_tooltip"], total_cards),
                "show_streak_count": ("Streak", maturity),
                "show_streak_pct": ("Streak %", maturity_pct)
            }

            grid_rows = ""
            for key in col_order:
                if key in data_map and cfg.get(key, True):
                    icon, val = data_map[key]
                    grid_rows += f'<div class="grid-stat-row" style="{text_shadow_style}"><span>{icon}</span><span>{val}</span></div>'

            grid_html += f'''
            <div class="grid-item" style="{bg_style} {depth_style}">
                {cover_html}
                <div class="grid-header" style="{text_shadow_style}">
                    <div style="display:flex; align-items:center; gap:4px; overflow:hidden;">
                        <span style="font-size:14px;">{rpg_icon}</span>
                        <span class="grid-title">{name}</span>
                    </div>
                    {xp_display}
                </div>
                {progress_html}
                <div class="grid-counts" style="{text_shadow_style}">
                    <span class="n{'' if new else ' z'}">{new}</span>
                    <span class="l{' z' if not lrn else ''}">{lrn}</span>
                    <span class="d{' z' if not due else ''}">{due}</span>
                </div>
                <div class="grid-details">
                    {grid_rows}
                </div>
            </div>
            '''
        
        grid_html += '</div>'
        return grid_html

    # --- RENDERIZAÇÃO: MODO LISTA (TABLE) ---
    def render_list_view():
        # Cálculos Globais para o Rodapé
        avg_global_str = "-"
        if totals["reviews"] > 0:
            avg_global = (totals["time_ms"] / 1000) / totals["reviews"]
            avg_global_str = f"{avg_global:.1f}s"

        global_speed_str = "-"
        if totals["time_ms"] > 0:
            global_time_min = totals["time_ms"] / 60000
            if global_time_min > 0:
                global_cpm = totals["reviews"] / global_time_min
                global_speed_str = f"{global_cpm:.1f}"

        global_retention_str = "-"
        if totals["reviews"] > 0:
            global_retention_str = f"{(totals['passed'] / totals['reviews']) * 100:.0f}%"

        streak_footer_count = totals["streak"]
        streak_footer_pct = "0%"
        if totals["cards"] > 0:
            pct = (totals["streak"] / totals["cards"]) * 100
            streak_footer_pct = f"{pct:.0f}%"

        stars_footer = ""
        if totals["stars"] > 0:
            stars_footer = f'<span style="color:#FFD700; font-weight:bold; margin-left:2px;">⭐{totals["stars"]}</span>'

        total_time_footer = format_time_str(totals.get("time_seconds", 0))

        # Larguras das colunas fixas
        w_nm = col_widths.get("col_name", 300)
        style_nm = f"width:{w_nm}px;"
        w_st = col_widths.get("col_counts", 160)
        style_st = f"width:{w_st}px;"
        w_op = col_widths.get("col_opts", 50)
        style_op = f"width:{w_op}px;"
        w_ord = col_widths.get("col_ord", 40)
        style_ord = f"width:{w_ord}px;"

        h_cols = ""
        f_cols = ""

        # Definição das colunas
        cols_def = [
            ("show_time", "⏱️", total_time_footer),
            ("show_avg_time", "s/card", avg_global_str),
            ("show_speed", "🚀", global_speed_str),
            ("show_goal", "🎯", f"{totals['goal']}{stars_footer}"),
            ("show_retention", "% Hj", global_retention_str),
            ("show_ease", "⚖️", "-"),
            ("show_leeches", "🩸", totals["leeches"] if totals["leeches"] > 0 else ""),
            ("show_tomorrow", "🔮", totals["tomorrow"]),
            ("show_total", lang["total_tooltip"], totals["cards"]),
            ("show_streak_count", "Streak (Qtd)", streak_footer_count),
            ("show_streak_pct", "Streak (%)", streak_footer_pct)
        ]

        col_order = cfg.get("column_order", [])
        col_map = {k: (t, v) for k, t, v in cols_def}
        
        for key in col_order:
            if key in col_map and cfg.get(key, True):
                title, foot_val = col_map[key]
                
                # Header customizado
                header_content = title
                if key == "show_leeches":
                    header_content = f'<div style="font-size:11px; color:{text_color}; font-weight:bold; margin-bottom:2px;">{leech_val}</div>{title}'
                elif key == "show_streak_count":
                    header_content = f'<div style="font-size:11px; color:{text_color}; font-weight:bold; margin-bottom:2px;">{streak_val}</div>{title}'
                
                w = col_widths.get(key, 0)
                w_style = f"width:{w}px;" if w > 0 else ""
                
                h_cols += f'<td class="col-header" style="font-size:9px; text-align:center; color:{muted_color}; vertical-align:bottom; padding-bottom:4px; position:relative; {w_style}">{header_content}</td>'
                f_cols += f'<td style="text-align:center; color:{text_color}; font-size:11px;">{foot_val}</td>'

        total_root_decks = sum(1 for r in rows_data if r["depth"] == 0)
        
        rows_html = f'''
        <tr style="font-size:10px; color:{muted_color}; line-height:1;">
            <td class="col-header" style="position:relative; {style_ord}; text-align:center; vertical-align:bottom; padding-bottom:4px;">
                <span style="font-weight:bold; font-size:11px; color:{text_color}">#{total_root_decks}</span>
            </td>
            <td class="col-header" style="position:relative; {style_nm}"></td>
            <td class="st col-header" style="padding-bottom:2px; vertical-align:bottom; position:relative; {style_st}">
                <span class="n" style="color:#7cf; font-weight:bold;">{lang["new"]}</span>
                <span class="l" style="color:#f99; font-weight:bold;">{lang["learn"]}</span>
                <span class="d" style="color:#4CAF50; font-weight:bold;">{lang["review"]}</span>
            </td>
            {h_cols}
            <td class="col-header" style="position:relative; {style_op}"></td>
        </tr>
        <tr style="background:rgba(127,127,127,0.1); border-bottom:1px solid {border_color}; font-weight:bold;">
            <td></td>
            <td class="nm" style="text-align:right; padding-right:10px; color:{text_color}; font-style:italic;">{lang["totals"]}</td>
            <td class="st">
                <span class="n">{totals['new']}</span>
                <span class="l">{totals['lrn']}</span>
                <span class="d">{totals['due']}</span>
            </td>
            {f_cols}
            <td></td>
        </tr>
        '''

        depth_counters = {}
        last_depth = -1

        for row in rows_data:
            name = row["name"]
            depth = row["depth"]
            new, lrn, due = row["counts"]
            maturity, retention, total_cards, tomorrow, done_today, speed, ease, leeches, mature_count_int, avg_time, _, total_stars, _, ease_counts, maturity_pct = row["stats"]
            
            # RPG Stats
            hp, xp, hp_pct = row.get("rpg", (100, 0, 100))
            
            deck_goal = row["goal"]
            row_bg = row["bg_color"]
            has_children = row["has_children"]
            expanded = row["expanded"]
            recursive_seconds = row.get("recursive_seconds", 0)

            if depth > last_depth: depth_counters[depth] = 0
            if depth not in depth_counters: depth_counters[depth] = 0
            depth_counters[depth] += 1
            current_count = depth_counters[depth]
            last_depth = depth

            idx_display = f'<span style="font-weight:bold; font-size:11px;">{current_count}</span>' if depth == 0 else f'<span style="font-size:9px; opacity:0.7;">{current_count}</span>'
            style_bg = f'style="background-color:{row_bg} !important;"' if row_bg else ""
            sym = "[-]" if expanded and has_children else "[+]" if has_children else ""
            expander = f'<span style="color:#4da6ff; margin-right:6px; font-weight:bold">{sym}</span>' if has_children else '<span style="display:inline-block; width:16px"></span>'
            rpg_icon = get_rpg_icon(mature_count_int, total_cards)
            name_html = f'<span style="margin-right:4px;">{rpg_icon}</span><span style="font-weight:bold;">{name}</span>'

            # RPG Visuals
            hp_color = "#5aff5a"
            if hp < 30: hp_color = "#ff5a5a"
            elif hp < 70: hp_color = "#ff9d5a"
            
            hp_tooltip = f"{lang['deck_hp']}: {hp}/100"
            xp_display = f'<span title="{hp_tooltip}" style="cursor:help; font-size:9px; color:#FFD700; margin-left:4px; font-weight:bold;">+{xp} XP</span>' if xp >= 0 else f'<span title="{hp_tooltip}" style="cursor:help; font-size:9px; color:#ff5a5a; margin-left:4px; font-weight:bold;">{xp} XP</span>'
            
            hp_html = f'''
            <div style="width: 100%; height: 6px; background: rgba(0,0,0,0.3); margin-top: 3px; border-radius: 3px; overflow: hidden; cursor: help;" title="{hp_tooltip}">
                <div style="width: {hp_pct}%; height: 100%; background: {hp_color};"></div>
            </div>
            '''

            progress_html = ""
            if cfg.get("show_progress", True):
                remaining = new + lrn + due
                daily_total = done_today + remaining
                daily_pct = 0
                if daily_total > 0: daily_pct = (done_today / daily_total) * 100
                elif done_today > 0: daily_pct = 100
                
                is_goal_met = done_today >= deck_goal and deck_goal > 0
                if is_goal_met: bar_color = "#FFD700"
                elif daily_pct < 50: bar_color = "#ff5a5a"
                elif daily_pct < 100: bar_color = "#4da6ff"
                else: bar_color = "#5aff5a"
                
                breakdown = f"🟥 {ease_counts[1]}   🟧 {ease_counts[2]}   🟩 {ease_counts[3]}   🟦 {ease_counts[4]}"
                tooltip_text = lang["deck_progress_tooltip"].format(deck_name=name, pct=int(daily_pct), done=done_today, total=daily_total) + f"&#10;{breakdown}"
                progress_html = f'''
                <div style="width: 100%; height: 6px; background: {progress_bg}; margin-top: 2px; border-radius: 3px; overflow: hidden; cursor: help;" title="{tooltip_text}">
                    <div style="width: {daily_pct}%; height: 100%; background: {bar_color};"></div>
                </div>
                '''

            time_str = "-"
            if cfg.get("show_time", True): time_str = format_time_str(recursive_seconds)
            stars_html = f'<span style="color:#FFD700; font-size:10px; margin-left:2px; font-weight:bold;">⭐{total_stars}</span>' if total_stars > 0 else ""

            cols_html = ""
            leech_style = f'color:{"#ff5a5a" if leeches > 0 else muted_color}'
            tom_style = f'color:{"#ff9999" if tomorrow > 50 else muted_color}'

            # --- CORREÇÃO AQUI: Formatação das strings de tooltip ---
            tooltip_streak = lang["streak_count_tooltip"].format(count=streak_val)
            tooltip_leech = lang["leech_tooltip"].format(count=leech_val)
            tooltip_streak_pct = lang["streak_pct_tooltip"]

            row_data_map = {
                "show_time": (time_str, "inf", f'title="{lang["estimated_time_tooltip"]}"'),
                "show_avg_time": (avg_time, "inf", f'title="{lang["avg_seconds_per_card"]}"'),
                "show_speed": (speed, "inf", f'title="{lang["speed_tooltip"]}"'),
                "show_goal": (f"{deck_goal} {stars_html}", "inf", 'style="white-space:nowrap;"'),
                "show_retention": (retention, "inf", f'title="{lang["retention_rate_today"]}"'),
                "show_ease": (ease, "inf", f'title="{lang["avg_ease_tooltip"]}"'),
                "show_leeches": (leeches, "inf", f'title="{tooltip_leech}" style="{leech_style}"'),
                "show_tomorrow": (tomorrow, "inf", f'style="{tom_style}"'),
                "show_total": (total_cards, "inf", f'title="{lang["total_tooltip"]}"'),
                "show_streak_count": (maturity, "mat", f'title="{tooltip_streak}"'),
                "show_streak_pct": (maturity_pct, "mat", f'title="{tooltip_streak_pct}"')
            }

            for key in col_order:
                if key in row_data_map and cfg.get(key, True):
                    val, cls, extra = row_data_map[key]
                    w = col_widths.get(key, 0)
                    w_style = f"width:{w}px;" if w > 0 else ""
                    
                    # --- CORREÇÃO AQUI: Separação de style e outros atributos ---
                    if extra.strip().startswith('style="'):
                        style_content = extra.strip()[7:-1]
                        cols_html += f'<td class="{cls}" style="position:relative; {w_style} {style_content}">{val}</td>'
                    else:
                        cols_html += f'<td class="{cls}" style="position:relative; {w_style}" {extra}>{val}</td>'

            rows_html += f'''
            <tr class="pr" {style_bg}>
                <td style="position:relative; {style_ord}; text-align:center; font-size:10px; color:{muted_color};">{idx_display}</td>
                <td class="nm" style="padding-left:{depth*20}px; position:relative; {style_nm}">
                    <div style="display:flex; align-items:center; overflow:hidden;">{expander}{name_html}{xp_display}</div>
                    {hp_html}
                    {progress_html}
                </td>
                <td class="st" style="position:relative; {style_st}">
                    <span class="n{'' if new else ' z'}">{new}</span>
                    <span class="l{' z' if not lrn else ''}">{lrn}</span>
                    <span class="d{' z' if not due else ''}">{due}</span>
                </td>
                {cols_html}
                <td class="op" style="position:relative; {style_op}">⚙</td>
            </tr>'''
        
        return f'<table>{rows_html}</table>'

    # Seleciona o conteúdo baseado no modo
    content_html = render_grid_view() if is_grid else render_list_view()

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{lang["html_report_title"]}</title>
        <style>
            :root {{
                --bg: {bg_color};
                --text-fg: {text_color};
                --text-muted: {muted_color};
                --border: {border_color};
                --header-bg: {header_bg};
                --progress-bg: {progress_bg};
                --input-bg: {input_bg};
            }}
            body {{ background: var(--bg); color: var(--text-fg); font-family: sans-serif; padding: 20px; overflow-y: auto; }}
            
            .pdb-outer {{ display: flex; justify-content: center; width: 100%; }}
            .pdb {{ 
                background: var(--bg); color: var(--text-fg); border: 1px solid var(--border); 
                border-radius: 8px; margin-bottom: 16px; box-sizing: border-box; 
                position: relative;
                width: {table_width_style};
                min-width: fit-content;
                max-width: 100%;
                max-height: none !important;
                overflow: visible !important;
                flex: 0 0 auto;
            }}
            .pdh {{ 
                background: var(--header-bg); color: var(--text-fg); padding: 8px 14px; font-weight: bold; 
                display: flex; justify-content: space-between; align-items: center;
                border-bottom: 1px solid var(--border); 
                position: sticky; top: 0; z-index: 100;
            }}
            
            /* Table Styles */
            td {{ padding: 4px; white-space: nowrap; }}
            td.nm {{ overflow: hidden; text-overflow: ellipsis; max-width: 400px; }}
            td.st {{ white-space: nowrap; text-align: right; padding-right: 10px; min-width: 165px; }}
            .n, .l, .d, .z {{ display: inline-block; width: 45px; text-align: right; margin-left: 5px; }}
            .n{{color:#7cf}} .l{{color:#f99}} .d{{color:#4CAF50}} .z{{color:var(--text-muted)}}
            td.mat {{ width: 75px; text-align: center; color: var(--text-muted); font-size: 11px; white-space: nowrap; }}
            td.inf {{ width: 35px; text-align: center; color: var(--text-muted); font-size: 11px; }}
            tr.pr {{ border-bottom: 1px solid rgba(127,127,127,0.1); }}
            table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
            .col-header {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

            /* Grid Styles */
            .grid-container {{
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                padding: 10px;
                justify-content: flex-start;
            }}
            .grid-item {{
                background: var(--input-bg);
                border: 1px solid var(--border);
                border-radius: 6px;
                padding: 8px;
                width: 160px;
                display: flex;
                flex-direction: column;
                gap: 5px;
                position: relative;
                overflow: hidden;
            }}
            .grid-cover {{
                position: absolute;
                top: 0; left: 0; width: 100%; height: 100%;
                object-fit: cover; z-index: 0;
            }}
            .grid-overlay {{
                position: absolute;
                top: 0; left: 0; width: 100%; height: 100%;
                background: linear-gradient(to bottom, rgba(0,0,0,0.2) 0%, rgba(0,0,0,0.8) 100%);
                z-index: 1;
            }}
            .grid-header {{
                display: flex; justify-content: space-between; align-items: center;
                font-weight: bold; font-size: 12px; border-bottom: 1px solid var(--border);
                padding-bottom: 4px; margin-bottom: 2px; position: relative; z-index: 2;
            }}
            .grid-title {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-grow: 1; margin: 0 4px; }}
            .grid-counts {{
                display: flex; justify-content: space-between; font-size: 11px;
                margin-bottom: 4px; position: relative; z-index: 2;
            }}
            .grid-details {{ display: flex; flex-direction: column; gap: 2px; position: relative; z-index: 2; }}
            .grid-stat-row {{
                display: flex; justify-content: space-between; font-size: 10px;
                color: var(--text-muted); border-bottom: 1px solid rgba(127,127,127,0.1); padding: 1px 0;
            }}
        </style>
    </head>
    <body>
        <div class="pdb">
            <div class="pdh">
                <div style="flex-grow:0; white-space:nowrap; margin-right:10px;">{lang["pinned_decks_report"]} ({lang['grid'] if is_grid else lang['list']})</div>
                {global_level_html}
                {daily_html}
            </div>
            {content_html}
        </div>
    </body>
    </html>
    """
    
    return full_html