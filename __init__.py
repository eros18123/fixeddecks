
# __init__.py
import os
import re
import json
import itertools
import math
import webbrowser
import tempfile
import datetime
import time
import html as html_lib
from operator import itemgetter
from collections import defaultdict
from aqt import mw, gui_hooks, dialogs
from aqt.qt import *
from aqt.utils import getFile, tooltip
from aqt.theme import theme_manager
import base64

# Importa o módulo local de HTML e os arquivos de idioma
from . import html as report_html
from . import portugues, ingles

ADDON_DIR = os.path.dirname(__file__)
ADDON_FOLDER_NAME = os.path.basename(ADDON_DIR)
CONFIG_FILE = os.path.join(ADDON_DIR, "pinned_config.json")

# Lista padrão de ordem das colunas
DEFAULT_COL_ORDER = [
    "show_time", "show_avg_time", "show_speed", "show_goal", 
    "show_retention", "show_ease", "show_leeches", 
    "show_tomorrow", "show_total", "show_streak_count", "show_streak_pct"
]

DEFAULT_CONFIG = {
    "pinned_ids": [],
    "expanded_ids": [],
    "child_sort_order": {},
    "deck_goals": {},
    "deck_colors": {},
    "deck_covers": {},
    "col_widths": {},
    "column_order": DEFAULT_COL_ORDER,
    "backup_visibility": {},
    "table_width": 98,
    "table_max_height": 400,
    "is_collapsed": False,
    "hide_original_list": False,
    "is_grid_view": False,
    "streak_threshold": 20,
    "leech_threshold": 10,
    "chart_days": 7,
    "show_charts": True,
    "language": "pt",
    "stats_history": {}, 
    
    # --- CONFIGURAÇÃO DE VISIBILIDADE PADRÃO ---
    "show_progress": True,
    "show_retention": True,
    "show_ease": True,
    "show_total": True,
    "show_streak_count": True,
    "show_streak_pct": True,
    
    # Colunas desativadas por padrão
    "show_time": False,
    "show_avg_time": False,
    "show_speed": False,
    "show_leeches": False,
    "show_tomorrow": False,
    "show_goal": False,
    
    "last_sort_col": None,
    "last_sort_desc": True
}

STATS_CACHE = {}
RPG_CACHE = {}
LANG = {}
SELECTED_FOR_STUDY = set()
TEMP_DECK_NAME = "Estudo Personalizado (Temporário)"

def load_language():
    global LANG
    cfg = load_config()
    lang_code = cfg.get("language", "pt")
    if lang_code == "en":
        LANG = ingles.t
    else:
        LANG = portugues.t

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            conf = json.load(f)
        
        for k, v in DEFAULT_CONFIG.items():
            if k not in conf:
                conf[k] = v
        
        current_order = conf.get("column_order", [])
        if "show_streak" in current_order:
            idx = current_order.index("show_streak")
            current_order.pop(idx)
            if "show_streak_count" not in current_order: current_order.insert(idx, "show_streak_count")
            if "show_streak_pct" not in current_order: current_order.insert(idx+1, "show_streak_pct")
            
        missing = [c for c in DEFAULT_COL_ORDER if c not in current_order]
        if missing:
            conf["column_order"] = current_order + missing
            
        return conf
    except:
        return DEFAULT_CONFIG.copy()

def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print("Erro ao salvar config:", e)

def toggle_setting(key):
    c = load_config()
    c[key] = not c.get(key, True)
    save_config(c)
    mw.deckBrowser.refresh()

def clear_stats_cache():
    global STATS_CACHE, RPG_CACHE
    STATS_CACHE = {}
    RPG_CACHE = {}

def image_to_base64(filename):
    filepath = os.path.join(ADDON_DIR, filename)
    if not os.path.exists(filepath):
        return ""
    ext = filename.split('.')[-1].lower()
    mime_type = f"image/{'jpeg' if ext == 'jpg' else ext}"
    with open(filepath, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return f"data:{mime_type};base64,{encoded_string}"

# ==================== LÓGICA DE DADOS E TEMPO ====================

def format_time_str(total_seconds):
    if total_seconds <= 0: return "-"
    if total_seconds < 60: return f"{int(total_seconds)}s"
    elif total_seconds < 3600: return f"{int(total_seconds / 60)}m"
    else:
        hours = int(total_seconds / 3600)
        minutes = int((total_seconds % 3600) / 60)
        if minutes > 0: return f"{hours}h {minutes}m"
        return f"{hours}h"

def get_recursive_time_seconds(node):
    my_seconds = (node.new_count * 15) + (node.learn_count * 10) + (node.review_count * 8)
    children_seconds = 0
    for child in node.children:
        children_seconds += get_recursive_time_seconds(child)
    return max(my_seconds, children_seconds)

def get_daily_stats():
    start_timestamp = (mw.col.sched.day_cutoff - 86400) * 1000
    rows = mw.col.db.all(f"""
        SELECT ease, count()
        FROM revlog
        WHERE id > {start_timestamp}
        GROUP BY ease
    """)
    stats = {1: 0, 2: 0, 3: 0, 4: 0}
    for ease, count in rows:
        if ease in stats:
            stats[ease] = count
    return stats

def get_last_review_time():
    try:
        last_ms = mw.col.db.scalar("SELECT id FROM revlog ORDER BY id DESC LIMIT 1")
        if last_ms:
            dt = datetime.datetime.fromtimestamp(last_ms / 1000.0)
            return dt.strftime("%H:%M:%S")
    except:
        pass
    return "--:--:--"

def get_global_streak():
    try:
        cutoff = mw.col.sched.day_cutoff
        query = f"""
            SELECT DISTINCT cast((id/1000 - {cutoff}) / 86400 as int) as day_num
            FROM revlog
            ORDER BY day_num DESC
        """
        days = mw.col.db.list(query)
        if not days: return 0
        streak = 0
        current_check = 0 
        if 0 in days: current_check = 0
        elif -1 in days: current_check = -1
        else: return 0
        while current_check in days:
            streak += 1
            current_check -= 1
        return streak
    except:
        return 0

def get_historical_stars(ids_str, goal):
    if goal <= 0 or not ids_str: return 0
    cutoff = mw.col.sched.day_cutoff
    query = f"""
        SELECT count() 
        FROM revlog 
        WHERE cid IN (SELECT id FROM cards WHERE did IN ({ids_str}))
        GROUP BY cast((id / 1000 - {cutoff}) / 86400 as int)
    """
    try:
        day_counts = mw.col.db.list(query)
        total_stars = sum(count // goal for count in day_counts)
        return total_stars
    except:
        return 0

def get_rpg_icon(mature_count, total_cards):
    if total_cards == 0:
        return "🌱", f"{LANG.get('rpg_icon_level_0', 'Novato')} (0%)"
    pct = (mature_count / total_cards) * 100
    if pct <= 10: return "🌱", f"{LANG.get('rpg_icon_level_0', 'Novato')} ({int(pct)}%)"
    elif pct <= 20: return "🌿", f"{LANG.get('rpg_icon_level_1', 'Iniciante')} ({int(pct)}%)"
    elif pct <= 30: return "🍃", f"{LANG.get('rpg_icon_level_2', 'Praticante')} ({int(pct)}%)"
    elif pct <= 40: return "🌳", f"{LANG.get('rpg_icon_level_3', 'Estudante')} ({int(pct)}%)"
    elif pct <= 50: return "🌲", f"{LANG.get('rpg_icon_level_4', 'Dedicado')} ({int(pct)}%)"
    elif pct <= 60: return "🌴", f"{LANG.get('rpg_icon_level_5', 'Experiente')} ({int(pct)}%)"
    elif pct <= 70: return "🌸", f"{LANG.get('rpg_icon_level_6', 'Proficiente')} ({int(pct)}%)"
    elif pct <= 80: return "🌻", f"{LANG.get('rpg_icon_level_7', 'Especialista')} ({int(pct)}%)"
    elif pct <= 90: return "💎", f"{LANG.get('rpg_icon_level_8', 'Mestre')} ({int(pct)}%)"
    else: return "👑", f"{LANG.get('rpg_icon_level_9', 'Lenda')} ({int(pct)}%)"

# ==================== LÓGICA RPG ====================

def _calculate_xp_from_reviews(reviews, leech_thr):
    """Helper function to calculate XP from a list of review rows."""
    xp = 0
    streak = 0
    fail_streak = 0
    passed_reviews = 0
    
    prev_time_cache = {}

    for rid, cid, ease, time_ms, factor, lapses, ivl, reps in reviews:
        if factor >= 2500: base_xp = 1
        else: base_xp = int((2600 - factor) / 50)

        if ease == 1:
            xp -= (base_xp * 2)
            streak = 0
            fail_streak += 1
        else:
            passed_reviews += 1
            fail_streak = 0
            streak += 1
            current_xp_gain = base_xp
            if (reps > 10 and factor > 1900) or (ivl > 100): current_xp_gain = 0
            else:
                if lapses >= leech_thr: current_xp_gain += 15 
                if current_xp_gain > 0:
                    if streak >= 10: current_xp_gain *= 2.0
                    elif streak >= 5: current_xp_gain *= 1.5
            
            if cid not in prev_time_cache:
                prev_time_ms = mw.col.db.scalar(f"SELECT time FROM revlog WHERE cid = {cid} AND id < {rid} ORDER BY id DESC LIMIT 1")
                prev_time_cache[cid] = prev_time_ms
            else:
                prev_time_ms = prev_time_cache[cid]

            if prev_time_ms:
                diff = time_ms - prev_time_ms
                if diff < -500: current_xp_gain += 2 
                elif diff > 500:
                    current_xp_gain -= 2 
                    if current_xp_gain < 0: current_xp_gain = 0
            
            xp += int(current_xp_gain)
            prev_time_cache[cid] = time_ms

    total_reviews = len(reviews)
    if total_reviews > 5:
        retention = passed_reviews / total_reviews
        if retention >= 0.95: xp += 50 
        elif retention < 0.80: xp -= 50 

    return int(xp)

def get_rpg_daily_stats(did):
    cfg = load_config()
    leech_thr = cfg.get("leech_threshold", 10)
    cutoff = mw.col.sched.day_cutoff
    cache_key = (did, cutoff, leech_thr, "rpg_time_v5")
    if cache_key in RPG_CACHE: return RPG_CACHE[cache_key]

    try:
        start_timestamp = (cutoff - 86400) * 1000
        query = f"""
            SELECT revlog.id, revlog.cid, revlog.ease, revlog.time, cards.factor, cards.lapses, cards.ivl, cards.reps
            FROM revlog 
            JOIN cards ON revlog.cid = cards.id
            WHERE revlog.id > {start_timestamp} 
            AND cards.did = {did}
            ORDER BY revlog.id ASC
        """
        rows = mw.col.db.all(query)
        
        hp = 100
        fail_streak = 0
        
        for rid, cid, ease, time_ms, factor, lapses, ivl, reps in rows:
            damage = 15 + int((2600 - factor) / 100)
            if ease == 1:
                hp -= damage
                fail_streak += 1
                if fail_streak >= 3: hp -= 25
            else:
                fail_streak = 0
                heal = 1
                if ease >= 3: heal = 2
                hp = min(100, hp + heal)
        
        xp = _calculate_xp_from_reviews(rows, leech_thr)
        hp = max(0, hp)

        children = mw.col.decks.children(did)
        children_xp_sum = 0
        min_child_hp = 100
        has_children = False

        for name, child_id in children:
            has_children = True
            c_hp, c_xp, c_hp_pct = get_rpg_daily_stats(child_id)
            children_xp_sum += c_xp
            if c_hp < min_child_hp: min_child_hp = c_hp

        final_xp = int(xp + children_xp_sum)
        final_hp = hp
        if not rows and has_children: final_hp = min_child_hp
        
        result = (final_hp, final_xp, final_hp)
        RPG_CACHE[cache_key] = result
        return result
    except Exception as e:
        return (100, 0, 100)

def get_global_rpg_level(total_xp):
    levels = [
        (0, LANG.get("level_0_name", "Aldeão"), "#a0a0a0"),
        (100, LANG.get("level_1_name", "Recruta"), "#cd7f32"),
        (300, LANG.get("level_2_name", "Soldado"), "#c0c0c0"),
        (600, LANG.get("level_3_name", "Veterano"), "#ffd700"),
        (1000, LANG.get("level_4_name", "Elite"), "#00ced1"),
        (1500, LANG.get("level_5_name", "Mestre"), "#9932cc"),
        (2500, LANG.get("level_6_name", "Grão-Mestre"), "#ff4500"),
        (4000, LANG.get("level_7_name", "LENDA"), "#ff00ff")
    ]
    if total_xp < 0: return LANG.get("level_cursed", "Amaldiçoado"), "#555", 0, 0, 0, 100
    if total_xp >= 4000: return LANG.get("level_7_name", "LENDA"), "#ff00ff", 1.0, 1.0, total_xp, "∞"

    current_idx = 0
    for i, (threshold, _, _) in enumerate(levels):
        if total_xp >= threshold: current_idx = i
        else: break
    
    floor, title, color = levels[current_idx]
    ceiling = levels[current_idx + 1][0]
    xp_needed_for_level = ceiling - floor
    xp_progress_in_level = total_xp - floor
    pct_level = xp_progress_in_level / xp_needed_for_level
    pct_global = total_xp / 4000.0
    return title, color, pct_level, pct_global, xp_progress_in_level, xp_needed_for_level

def get_global_daily_summary(days, dids=None):
    """Calculates cards reviewed and XP gained for each of the last N days."""
    cfg = load_config()
    leech_thr = cfg.get("leech_threshold", 10)
    cutoff = mw.col.sched.day_cutoff
    
    start_timestamp = (cutoff - (days * 86400)) * 1000
    
    did_filter = ""
    if dids:
        dids_str = ",".join(map(str, dids))
        if dids_str:
            did_filter = f"AND cards.did IN ({dids_str})"

    try:
        query = f"""
            SELECT 
                revlog.id, revlog.cid, revlog.ease, revlog.time, 
                cards.factor, cards.lapses, cards.ivl, cards.reps,
                cast((revlog.id/1000 - {cutoff}) / 86400 as int) as day_offset
            FROM revlog 
            JOIN cards ON revlog.cid = cards.id
            WHERE revlog.id > {start_timestamp} {did_filter}
            ORDER BY revlog.id ASC
        """
        rows = mw.col.db.all(query)
        
        reviews_by_day = defaultdict(list)
        for r in rows:
            day_offset = r[-1]
            reviews_by_day[day_offset].append(r[:-1])
            
        results = []
        for i in range(days - 1, -1, -1):
            day_offset = -i
            
            ts = cutoff + (day_offset * 86400) - 43200
            date_obj = datetime.datetime.fromtimestamp(ts)
            date_key = date_obj.strftime("%d/%m")
            
            day_reviews = reviews_by_day.get(day_offset, [])
            
            cards_count = len(day_reviews)
            xp_gained = _calculate_xp_from_reviews(day_reviews, leech_thr) if day_reviews else 0
            
            results.append((date_key, cards_count, xp_gained))
            
        return results
    except Exception as e:
        print(f"Error in get_global_daily_summary: {e}")
        return []

# ==================== SESSÃO DE ESTUDO PERSONALIZADA ====================

def start_custom_study_session():
    global SELECTED_FOR_STUDY
    if not SELECTED_FOR_STUDY:
        tooltip(LANG.get("no_decks_selected", "Nenhum baralho selecionado."))
        return
    
    # Se for apenas um deck, seleciona e estuda direto
    if len(SELECTED_FOR_STUDY) == 1:
        did = list(SELECTED_FOR_STUDY)[0]
        mw.col.decks.select(did)
        # CORREÇÃO DO CRASH: Inicializa o timer do Anki
        if not hasattr(mw.col, "_startTime"):
            mw.col.startTimebox()
        mw.moveToState("review")
        SELECTED_FOR_STUDY.clear()
        return

    # Se forem vários, cria o deck temporário
    old_did = mw.col.decks.id_for_name(TEMP_DECK_NAME)
    if old_did: 
        mw.col.decks.remove([old_did])

    tree = mw.col.sched.deck_due_tree()
    cids_to_study = set()
    for did in SELECTED_FOR_STUDY:
        node = find_node(tree, did)
        if not node: continue
        deck_name = mw.col.decks.name(did)
        
        # Coleta os cards
        cids_to_study.update(mw.col.find_cards(f'deck:"{deck_name}" is:due'))
        cids_to_study.update(mw.col.find_cards(f'deck:"{deck_name}" is:learn'))
        
        limit_new = node.new_count
        if limit_new > 0:
            ids_new = mw.col.find_cards(f'deck:"{deck_name}" is:new', order="c.due asc")
            cids_to_study.update(ids_new[:limit_new])

    if not cids_to_study:
        tooltip(LANG.get("no_decks_selected", "Nada para estudar."))
        return

    # Cria o deck filtrado
    did = mw.col.decks.new_filtered(TEMP_DECK_NAME)
    deck = mw.col.decks.get(did)
    search_query = f"cid:{','.join(map(str, cids_to_study))}"
    deck['terms'] = [[search_query, 9999, 0]]
    deck['resched'] = True
    mw.col.decks.save(deck)
    mw.col.sched.rebuild_filtered_deck(did)
    
    mw.col.decks.set_current(did)
    
    # CORREÇÃO DO CRASH: Inicializa o timer antes de entrar na revisão
    if not hasattr(mw.col, "_startTime"):
        mw.col.startTimebox()
        
    SELECTED_FOR_STUDY.clear() # Limpa a seleção após iniciar
    mw.moveToState("review")

# ==================== ESTATÍSTICAS AVANÇADAS E GRÁFICOS ====================

def get_history_data(did, streak_threshold, current_vals, mode='retention'):
    cfg = load_config()
    history = cfg.get("stats_history", {}).get(str(did), {})
    cutoff = mw.col.sched.day_cutoff
    
    days_limit = cfg.get("chart_days", 7)
    if days_limit < 3: days_limit = 3 
    
    sql_data_map = {}
    try:
        deck_ids = mw.col.decks.deck_and_child_ids(did)
        if deck_ids:
            ids_str = ",".join(str(i) for i in deck_ids)
            
            query = f"""
                WITH RankedReviews AS (
                    SELECT 
                        id, cid, ease, type,
                        cast((id/1000 - {cutoff}) / 86400 as int) as day_offset,
                        ROW_NUMBER() OVER (PARTITION BY cid ORDER BY id) as rep_count
                    FROM revlog
                    WHERE cid IN (SELECT id FROM cards WHERE did IN ({ids_str}))
                )
                SELECT 
                    day_offset,
                    sum(case when ease > 1 then 1 else 0 end) as passed,
                    count() as total,
                    avg(case when ease > 0 then (select factor from cards where id = RankedReviews.cid) else 0 end) as avg_ease,
                    sum(case when type=0 then 1 else 0 end) as cnt_new,
                    sum(case when type=2 then 1 else 0 end) as cnt_lrn,
                    sum(case when type=1 then 1 else 0 end) as cnt_rev,
                    sum(case when rep_count >= {streak_threshold} AND type=1 then 1 else 0 end) as cnt_streak_attempt,
                    sum(case when rep_count >= {streak_threshold} AND type=1 AND ease > 1 then 1 else 0 end) as cnt_streak_success
                FROM RankedReviews
                GROUP BY day_offset
                ORDER BY day_offset DESC
                LIMIT {days_limit}
            """
            rows = mw.col.db.all(query)
            for r in rows:
                ts = cutoff + (r[0] * 86400) - 43200
                d_str = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                sql_data_map[d_str] = r
    except: pass

    data_points = []
    for i in range(days_limit - 1, -1, -1):
        target_ts = cutoff - ((i + 1) * 86400) + 43200 
        date_obj = datetime.datetime.fromtimestamp(target_ts)
        date_key = date_obj.strftime("%Y-%m-%d")
        display_date = date_obj.strftime("%d/%m")
        
        val = 0
        
        if mode in ['ease', 'retention']:
            if date_key in history:
                h = history[date_key]
                if mode == 'retention': val = h.get('retention', 0)
                elif mode == 'ease': val = h.get('ease', 0)
            
            if val == 0 and date_key in sql_data_map:
                r = sql_data_map[date_key]
                if mode == 'retention':
                    total = r[2]
                    passed = r[1]
                    val = round((passed / total * 100)) if total > 0 else 0
                elif mode == 'ease':
                    avg_e = r[3]
                    val = int(avg_e / 10) if avg_e else 0
            
            if val == 0:
                if mode == 'ease': val = current_vals.get('ease', 0)
                elif mode == 'retention': val = current_vals.get('retention', 0)

        else:
            if date_key in sql_data_map:
                r = sql_data_map[date_key]
                if mode == 'reviews':
                    val = (r[4], r[5], r[6])
                elif mode == 'streak_qty':
                    val = r[8]
                elif mode == 'streak_pct':
                    streak_attempt = r[7]
                    streak_success = r[8]
                    val = round((streak_success / streak_attempt * 100)) if streak_attempt > 0 else 0
            else:
                if mode == 'reviews': val = (0,0,0)
                else: val = 0
        
        data_points.append((display_date, val))

    return data_points

def generate_svg(data, title, color_line="#4da6ff", chart_type="line"):
    if not data: return ""
    
    calculated_width = (len(data) * 40) + 80
    width = max(260, calculated_width)
    
    height = 180
    margin_top = 50
    margin_bottom = 60
    margin_left = 35
    margin_right = 35
    
    graph_h = height - margin_top - margin_bottom
    graph_w = width - margin_left - margin_right
    
    if chart_type == "grouped_bar":
        all_vals = []
        for d, v in data:
            all_vals.extend(v)
        max_val = max(all_vals) if all_vals else 10
        min_val = 0
    else:
        vals = [v for d, v in data]
        max_val = max(vals) if vals else 100
        min_val = min(vals) if vals else 0
    
    if chart_type == "line":
        display_min = max(0, min_val - 10)
        display_max = 100
        if max_val > 100: display_max = max_val * 1.05
        val_range = display_max - display_min
        if val_range == 0: val_range = 10
    else:
        display_min = 0
        display_max = max_val * 1.1 
        val_range = display_max
        if val_range == 0: val_range = 1

    points = []
    step_x = graph_w / (len(data) - 1) if len(data) > 1 else graph_w / 2
    
    svg_content = []
    svg_content.append(f'<text x="{width/2}" y="20" font-family="sans-serif" font-size="12" font-weight="bold" fill="#555" text-anchor="middle">{title}</text>')
    svg_content.append(f'<rect x="{margin_left}" y="{margin_top}" width="{graph_w}" height="{graph_h}" fill="rgba(0,0,0,0.03)" />')
    
    for i, item in enumerate(data):
        date_str = item[0]
        val = item[1]
        x = margin_left + (i * step_x) if len(data) > 1 else width/2
        
        svg_content.append(f'<line x1="{x}" y1="{margin_top}" x2="{x}" y2="{height-margin_bottom}" stroke="#000" stroke-opacity="0.1" stroke-width="1" />')
        
        if chart_type == "grouped_bar":
            c_new, c_lrn, c_rev = val
            alloc_width = (graph_w / len(data)) * 0.8
            group_width = min(alloc_width, 50)
            bar_width = group_width / 3
            
            x_new = x - bar_width
            x_lrn = x
            x_rev = x + bar_width
            
            h_new = (c_new / val_range) * graph_h
            h_lrn = (c_lrn / val_range) * graph_h
            h_rev = (c_rev / val_range) * graph_h
            
            y_base = margin_top + graph_h
            
            if h_new > 0:
                svg_content.append(f'<rect x="{x_new - bar_width/2}" y="{y_base - h_new}" width="{bar_width}" height="{h_new}" fill="#4da6ff" opacity="0.9" />')
                svg_content.append(f'<text x="{x_new}" y="{y_base - h_new - 2}" font-family="sans-serif" font-size="8" fill="#333" text-anchor="middle">{c_new}</text>')
            
            if h_lrn > 0:
                svg_content.append(f'<rect x="{x_lrn - bar_width/2}" y="{y_base - h_lrn}" width="{bar_width}" height="{h_lrn}" fill="#ff5a5a" opacity="0.9" />')
                svg_content.append(f'<text x="{x_lrn}" y="{y_base - h_lrn - 2}" font-family="sans-serif" font-size="8" fill="#333" text-anchor="middle">{c_lrn}</text>')
                
            if h_rev > 0:
                svg_content.append(f'<rect x="{x_rev - bar_width/2}" y="{y_base - h_rev}" width="{bar_width}" height="{h_rev}" fill="#5aff5a" opacity="0.9" />')
                svg_content.append(f'<text x="{x_rev}" y="{y_base - h_rev - 2}" font-family="sans-serif" font-size="8" fill="#333" text-anchor="middle">{c_rev}</text>')
            
        elif chart_type == "bar":
            pass
            
        else: # Line
            y = margin_top + graph_h - ((val - display_min) / val_range * graph_h)
            points.append((x, y))
            svg_content.append(f'<text x="{x}" y="{y-8}" font-family="sans-serif" font-size="10" fill="#333" text-anchor="middle">{val}</text>')

        svg_content.append(f'''
            <text transform="translate({x+3}, {height-10}) rotate(-90)" 
                  font-family="sans-serif" font-size="10" fill="#777" text-anchor="start">
                {date_str}
            </text>
        ''')

    if chart_type == "line" and points:
        path_d = f"M {points[0][0]} {points[0][1]}"
        for px, py in points[1:]:
            path_d += f" L {px} {py}"
        svg_content.append(f'<path d="{path_d}" fill="none" stroke="{color_line}" stroke-width="2" />')
        for px, py in points:
            svg_content.append(f'<circle cx="{px}" cy="{py}" r="3" fill="#fff" stroke="{color_line}" stroke-width="2" />')

    return f'''
    <svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" style="background:rgba(255,255,255,0.95); border-radius:4px; box-shadow:0 2px 5px rgba(0,0,0,0.1);">
        {"".join(svg_content)}
    </svg>
    '''

def generate_global_stats_svg(data):
    if not data: return ""
    
    num_days = len(data)
    bar_group_width = 65
    width = (num_days * bar_group_width) + 80
    height = 240
    # Margens para comportar labels e valores negativos
    margin = {'top': 60, 'bottom': 80, 'left': 40, 'right': 40}
    
    graph_h = height - margin['top'] - margin['bottom']
    graph_w = width - margin['left'] - margin['right']
    
    cards_vals = [d[1] for d in data]
    xp_vals = [d[2] for d in data]
    
    # BUGFIX: Considera valores absolutos para que a escala suporte barras negativas
    max_cards = max(cards_vals) if cards_vals else 1
    max_xp = max([abs(x) for x in xp_vals]) if xp_vals else 1
    
    max_val = max(max_cards, max_xp)
    if max_val == 0: max_val = 1

    svg_content = []
    title = LANG.get("daily_summary_chart_title", "Resumo Diário")
    svg_content.append(f'<text x="{width/2}" y="20" class="svg-title" text-anchor="middle">{title}</text>')
    
    # Legenda
    svg_content.append(f'<rect x="{width/2 - 70}" y="28" width="10" height="10" fill="#4da6ff" />')
    svg_content.append(f'<text x="{width/2 - 55}" y="37" class="svg-legend">{LANG.get("cards", "Cards")}</text>')
    svg_content.append(f'<rect x="{width/2 + 20}" y="28" width="10" height="10" fill="#ffd700" />')
    svg_content.append(f'<text x="{width/2 + 35}" y="37" class="svg-legend">XP</text>')

    step_x = graph_w / num_days
    bar_width = step_x * 0.35
    baseline = margin['top'] + graph_h # Linha de base onde as barras "nascem"

    for i, (date_str, cards, xp, level_name) in enumerate(data):
        x_base = margin['left'] + (i * step_x) + (step_x / 2)
        
        # Barra de Cards (sempre positiva)
        h_cards = (cards / max_val) * graph_h if cards > 0 else 0
        y_cards = baseline - h_cards
        svg_content.append(f'<rect x="{x_base - bar_width - 1}" y="{y_cards}" width="{bar_width}" height="{h_cards}" fill="#4da6ff"><title>{LANG.get("cards", "Cards")}: {cards}</title></rect>')
        if cards > 0:
            svg_content.append(f'<text x="{x_base - bar_width/2 - 1}" y="{y_cards - 3}" class="svg-bar-label" text-anchor="middle">{cards}</text>')

        # Barra de XP (Suporta valores negativos)
        h_xp = (abs(xp) / max_val) * graph_h
        if xp >= 0:
            y_xp = baseline - h_xp
            label_y = y_xp - 3
        else:
            # Se negativo, a barra começa no baseline e desce
            y_xp = baseline
            label_y = baseline + h_xp + 10 # Texto abaixo da barra negativa
            
        svg_content.append(f'<rect x="{x_base + 1}" y="{y_xp}" width="{bar_width}" height="{h_xp}" fill="#ffd700"><title>XP: {xp}</title></rect>')
        if xp != 0:
            svg_content.append(f'<text x="{x_base + bar_width/2 + 1}" y="{label_y}" class="svg-bar-label" text-anchor="middle">{xp}</text>')

        # Labels do Eixo X
        label_y_axis = height - margin["bottom"] + 15
        svg_content.append(f'''
            <text transform="translate({x_base - 5}, {label_y_axis}) rotate(-60)" 
                  class="svg-axis-label" text-anchor="end">{date_str}</text>
        ''')
        svg_content.append(f'''
            <text transform="translate({x_base - 5}, {label_y_axis + 15}) rotate(-60)" 
                  class="svg-level-label" text-anchor="end">{level_name}</text>
        ''')

    return f'''
    <div style="max-width: 600px; overflow-x: auto; padding-bottom: 10px; background: rgba(255,255,255,0.95); border-radius: 4px;">
        <svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
            <style>
                .svg-title {{ font-family: sans-serif; font-size: 14px; font-weight: bold; fill: #333; }}
                .svg-legend {{ font-family: sans-serif; font-size: 10px; fill: #555; }}
                .svg-bar-label {{ font-family: sans-serif; font-size: 9px; fill: #333; }}
                .svg-axis-label {{ font-family: sans-serif; font-size: 10px; fill: #777; }}
                .svg-level-label {{ font-family: sans-serif; font-size: 9px; font-weight: bold; fill: #333; }}
            </style>
            {"".join(svg_content)}
        </svg>
    </div>
    '''

def get_deck_stats_advanced(did, streak_threshold, leech_threshold, deck_goal):
    cutoff = mw.col.sched.day_cutoff
    cfg = load_config()
    chart_days = cfg.get("chart_days", 7)
    show_charts = cfg.get("show_charts", True)
    
    # Cache key atualizada para incluir o novo retorno
    cache_key = (did, streak_threshold, leech_threshold, deck_goal, cutoff, chart_days, show_charts, "v_cid_fix")
    if cache_key in STATS_CACHE: return STATS_CACHE[cache_key]

    try:
        deck_ids = mw.col.decks.deck_and_child_ids(did)
        if not deck_ids: 
            return ("-", "-", 0, 0, 0, "-", "-", 0, 0, "-", 0, 0, 0, {1:0, 2:0, 3:0, 4:0}, "-", "", "", "", "", "", "")
        ids_str = ",".join(str(i) for i in deck_ids)

        total_cards = mw.col.db.scalar(f"SELECT count() FROM cards WHERE did IN ({ids_str})")
        
        # BUSCA DOS IDs DOS CARTÕES COM STREAK (Garante sincronia com o Browser)
        mature_cids = mw.col.db.list(f"""
            SELECT c.id FROM cards c
            WHERE c.did IN ({ids_str})
            AND c.reps >= {streak_threshold}
            AND (
                SELECT count(*)
                FROM revlog r
                WHERE r.cid = c.id
                AND r.id > COALESCE((
                    SELECT MAX(id)
                    FROM revlog r2
                    WHERE r2.cid = c.id AND r2.ease = 1
                ), 0)
                AND r.ease > 1
            ) >= {streak_threshold}
        """)
        
        mature_count_int = len(mature_cids)
        mature_cids_str = ",".join(map(str, mature_cids))
        
        pct_mature = (mature_count_int / total_cards * 100) if total_cards > 0 else 0
        maturity_str = f"{mature_count_int}"
        maturity_pct_str = f"{pct_mature:.0f}%"

        start_timestamp = (cutoff - 86400) * 1000
        today_reviews = mw.col.db.all(f"""
            SELECT revlog.ease, revlog.time, cards.reps, revlog.type
            FROM revlog 
            JOIN cards ON revlog.cid = cards.id
            WHERE revlog.id > {start_timestamp} 
            AND cards.did IN ({ids_str})
        """)
        
        retention_str = "-"
        done_today_count = 0
        passed_today_count = 0
        speed_str = "-"
        avg_time_str = "-"
        total_time_ms = 0
        ease_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        
        current_retention_val = 0
        today_streak_qty = 0
        today_streak_attempts = 0
        
        if today_reviews:
            done_today_count = len(today_reviews)
            for ease, time, reps, type in today_reviews:
                if ease > 1: passed_today_count += 1
                total_time_ms += time
                if ease in ease_counts: ease_counts[ease] += 1
                
                if type == 1 and reps >= streak_threshold:
                    today_streak_attempts += 1
                    if ease > 1: today_streak_qty += 1
            
            current_retention_val = round(passed_today_count / done_today_count * 100)
            retention_str = f"{current_retention_val}%"

        today_streak_pct = 0
        if today_streak_attempts > 0:
            today_streak_pct = round(today_streak_qty / today_streak_attempts * 100)
            
        if done_today_count > 0:
            total_time_min = total_time_ms / 60000
            if total_time_min > 0:
                cpm = done_today_count / total_time_min
                speed_str = f"{cpm:.1f}"
            avg_sec = (total_time_ms / 1000) / done_today_count
            avg_time_str = f"{avg_sec:.1f}s"
        else:
            history_times = mw.col.db.list(f"""
                SELECT revlog.time 
                FROM revlog 
                JOIN cards ON revlog.cid = cards.id 
                WHERE cards.did IN ({ids_str}) 
                ORDER BY revlog.id DESC LIMIT 100
            """)
            if history_times:
                hist_count = len(history_times)
                hist_total_ms = sum(history_times)
                hist_avg_sec = (hist_total_ms / 1000) / hist_count
                avg_time_str = f"{hist_avg_sec:.1f}s"
                hist_total_min = hist_total_ms / 60000
                if hist_total_min > 0:
                    hist_cpm = hist_count / hist_total_min
                    speed_str = f"{hist_cpm:.1f}"

        tomorrow_due_date = mw.col.sched.today + 1
        tomorrow_count = mw.col.db.scalar(f"""
            SELECT count() FROM cards 
            WHERE did IN ({ids_str}) 
            AND queue = 2 
            AND due = {tomorrow_due_date}
        """)

        avg_ease = mw.col.db.scalar(f"SELECT avg(factor) FROM cards WHERE did IN ({ids_str}) AND queue != 0")
        ease_str = "-"
        current_ease_val = 0
        if avg_ease:
            current_ease_val = int(avg_ease / 10)
            ease_str = f"{current_ease_val}%"

        leech_count = mw.col.db.scalar(f"SELECT count() FROM cards WHERE did IN ({ids_str}) AND lapses >= {leech_threshold}")
        total_stars = get_historical_stars(ids_str, deck_goal)

        if "stats_history" not in cfg: cfg["stats_history"] = {}
        today_key = datetime.datetime.fromtimestamp(cutoff - 43200).strftime('%Y-%m-%d')
        did_str = str(did)
        if did_str not in cfg["stats_history"]: cfg["stats_history"][did_str] = {}
        
        saved_day = cfg["stats_history"][did_str].get(today_key, {})
        if saved_day.get("ease") != current_ease_val or saved_day.get("retention") != current_retention_val:
            cfg["stats_history"][did_str][today_key] = {"ease": current_ease_val, "retention": current_retention_val}
            save_config(cfg)

        retention_svg = reviews_svg = ease_svg = streak_qty_svg = streak_pct_svg = ""
        if show_charts:
            current_vals = {'ease': current_ease_val, 'retention': current_retention_val, 'streak_qty': today_streak_qty, 'streak_pct': today_streak_pct}
            ret_data = get_history_data(did, streak_threshold, current_vals, 'retention')
            rev_data = get_history_data(did, streak_threshold, current_vals, 'reviews')
            ease_data = get_history_data(did, streak_threshold, current_vals, 'ease')
            retention_svg = generate_svg(ret_data, LANG.get("chart_title_retention", "Retenção"), "#4da6ff", "line")
            reviews_svg = generate_svg(rev_data, LANG.get("chart_title_reviews", "Revisões"), "", "grouped_bar")
            ease_svg = generate_svg(ease_data, LANG.get("chart_title_ease", "Ease Médio"), "#FFD700", "line")

        result = (maturity_str, retention_str, total_cards, tomorrow_count, done_today_count, speed_str, ease_str, leech_count, mature_count_int, avg_time_str, total_time_ms, total_stars, passed_today_count, ease_counts, maturity_pct_str, retention_svg, reviews_svg, ease_svg, streak_qty_svg, streak_pct_svg, mature_cids_str)
        STATS_CACHE[cache_key] = result
        return result
    except Exception as e:
        return ("-", "-", 0, 0, 0, "-", "-", 0, 0, "-", 0, 0, 0, {1:0, 2:0, 3:0, 4:0}, "-", "", "", "", "", "", "")

# ==================== LÓGICA DE ORDENAÇÃO ====================

def sort_pinned_decks(col_name):
    cfg = load_config()
    pinned = cfg.get("pinned_ids", [])
    if not pinned: return

    if cfg.get("last_sort_col") == col_name:
        desc = not cfg.get("last_sort_desc", True)
    else:
        desc = True 
    
    cfg["last_sort_col"] = col_name
    cfg["last_sort_desc"] = desc

    sort_data = []
    streak_thr = cfg.get("streak_threshold", 20)
    leech_thr = cfg.get("leech_threshold", 10)
    tree = mw.col.sched.deck_due_tree()

    for did in pinned:
        node = find_node(tree, did)
        deck_name = node.name if node else mw.col.decks.name(did)
        val = 0 
        
        if col_name == "col_name":
            val = deck_name.lower()
        elif col_name == "col_counts":
            if node: val = node.new_count + node.learn_count + node.review_count
        elif col_name == "show_time":
            if node: val = get_recursive_time_seconds(node)
        else:
            deck_goal = cfg.get("deck_goals", {}).get(str(did), 100)
            stats = get_deck_stats_advanced(did, streak_thr, leech_thr, deck_goal)
            
            if col_name == "show_avg_time":
                if stats[4] > 0: val = stats[10] / stats[4]
            elif col_name == "show_speed":
                if stats[10] > 0: val = stats[4] / (stats[10] / 60000)
            elif col_name == "show_goal":
                val = deck_goal
            elif col_name == "show_retention":
                if stats[4] > 0: val = stats[12] / stats[4]
            elif col_name == "show_ease":
                try: val = int(stats[6].replace("%", ""))
                except: val = 0
            elif col_name == "show_leeches":
                val = stats[7]
            elif col_name == "show_tomorrow":
                val = stats[3]
            elif col_name == "show_total":
                val = stats[2]
            elif col_name == "show_streak_count":
                val = stats[8]
            elif col_name == "show_streak_pct":
                if stats[2] > 0: val = stats[8] / stats[2]

        sort_data.append((did, val, deck_name.lower()))

    def sort_key(item):
        did, val, name = item
        if isinstance(val, str):
            return (val, name) if not desc else (val, name)
        else:
            return (-val, name) if desc else (val, name)

    is_string_sort = (col_name == "col_name")
    sort_data.sort(key=sort_key, reverse=(desc if is_string_sort else False))

    cfg["pinned_ids"] = [item[0] for item in sort_data]
    save_config(cfg)
    mw.deckBrowser.refresh()

# ==================== MENU ====================

def set_deck_cover(did):
    path = getFile(mw, LANG.get("choose_cover_image", "Escolher Imagem"), None, f"{LANG.get('images', 'Imagens')} (*.jpg *.jpeg *.png *.gif *.webp)")
    if not path:
        return
    
    fname = mw.col.media.add_file(path)
    
    cfg = load_config()
    if "deck_covers" not in cfg:
        cfg["deck_covers"] = {}
    cfg["deck_covers"][str(did)] = fname
    save_config(cfg)
    mw.deckBrowser.refresh()
    tooltip(LANG.get("cover_set_success", "Capa definida!"))

def remove_deck_cover(did):
    cfg = load_config()
    if "deck_covers" in cfg and str(did) in cfg["deck_covers"]:
        del cfg["deck_covers"][str(did)]
        save_config(cfg)
        mw.deckBrowser.refresh()
        tooltip(LANG.get("cover_removed", "Capa removida."))

def on_options_menu(menu, deck_id):
    config = load_config()
    if deck_id in config.get("pinned_ids", []):
        cols_menu = menu.addMenu(LANG.get("customize_columns", "Colunas"))
        options = [
            ("show_progress", LANG.get("col_progress_bar", "Progresso")),
            ("show_time", LANG.get("col_estimated_time", "Tempo")),
            ("show_avg_time", LANG.get("col_avg_time", "Média")),
            ("show_speed", LANG.get("col_speed", "Velocidade")),
            ("show_goal", LANG.get("col_daily_goal", "Meta")),
            ("show_retention", LANG.get("col_retention_today", "Retenção")),
            ("show_ease", LANG.get("col_ease", "Ease")),
            ("show_leeches", LANG.get("col_leeches", "Sanguessugas")),
            ("show_tomorrow", LANG.get("col_tomorrow_forecast", "Amanhã")),
            ("show_total", LANG.get("col_total_cards", "Total")),
            ("show_streak_count", LANG.get("col_streak_count", "Streak")),
            ("show_streak_pct", LANG.get("col_streak_pct", "Streak %"))
        ]
        for key, label in options:
            act = cols_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(config.get(key, True))
            act.triggered.connect(lambda checked, k=key: toggle_setting(k))
        
        cols_menu.addSeparator()
        act_all = cols_menu.addAction(LANG.get("show_all_columns", "Mostrar Tudo"))
        act_all.triggered.connect(lambda: show_all_columns())

        if config.get("backup_visibility"):
            act_restore = cols_menu.addAction(LANG.get("restore_previous_view", "Restaurar"))
            act_restore.triggered.connect(lambda: restore_columns())

        color_menu = menu.addMenu(LANG.get("set_background_color", "Cor de Fundo"))
        colors = [
            (LANG.get("default", "Padrão"), ""),
            (LANG.get("red", "Vermelho"), "rgba(255, 80, 80, 0.15)"),
            (LANG.get("green", "Verde"), "rgba(80, 255, 80, 0.15)"),
            (LANG.get("blue", "Azul"), "rgba(80, 150, 255, 0.15)"),
            (LANG.get("yellow", "Amarelo"), "rgba(255, 255, 80, 0.15)"),
            (LANG.get("purple", "Roxo"), "rgba(200, 80, 255, 0.15)")
        ]
        for name, code in colors:
            a = color_menu.addAction(name)
            a.triggered.connect(lambda _, d=deck_id, c=code: set_deck_color(d, c))

        cover_menu = menu.addMenu(LANG.get("set_cover_image", "Capa"))
        act_set_cover = cover_menu.addAction(LANG.get("set_image", "Definir"))
        act_set_cover.triggered.connect(lambda: set_deck_cover(deck_id))
        act_rem_cover = cover_menu.addAction(LANG.get("remove_image", "Remover"))
        act_rem_cover.triggered.connect(lambda: remove_deck_cover(deck_id))

        menu.addSeparator()
        a = menu.addAction(LANG.get("unpin_from_top", "Desafixar"))
        a.triggered.connect(lambda: toggle_pin(deck_id, False))
    else:
        a = menu.addAction(LANG.get("pin_to_top", "Fixar"))
        a.triggered.connect(lambda: toggle_pin(deck_id, True))

def toggle_pin(did, pin=True):
    cfg = load_config()
    ids = cfg["pinned_ids"]
    if pin and did not in ids:
        ids.insert(0, did)
    elif not pin and did in ids:
        ids.remove(did)
    cfg["pinned_ids"] = ids
    save_config(cfg)
    mw.deckBrowser.refresh()

def set_deck_color(did, color_code):
    cfg = load_config()
    if "deck_colors" not in cfg: cfg["deck_colors"] = {}
    if color_code:
        cfg["deck_colors"][str(did)] = color_code
    else:
        if str(did) in cfg["deck_colors"]:
            del cfg["deck_colors"][str(did)]
    save_config(cfg)
    mw.deckBrowser.refresh()

def show_all_columns():
    c = load_config()
    backup = {}
    keys = ["show_time", "show_avg_time", "show_speed", "show_goal", "show_retention", 
            "show_ease", "show_leeches", "show_tomorrow", "show_total", "show_streak_count", "show_streak_pct"]
    for k in keys:
        backup[k] = c.get(k, True)
    c["backup_visibility"] = backup
    for k in keys:
        c[k] = True
    save_config(c)
    mw.deckBrowser.refresh()

def restore_columns():
    c = load_config()
    backup = c.get("backup_visibility", {})
    if not backup: return
    for k, v in backup.items():
        c[k] = v
    c["backup_visibility"] = {}
    save_config(c)
    mw.deckBrowser.refresh()

# ==================== RENDERIZAÇÃO (UI) ====================

def escape_for_html(text):
    return text.replace('"', '&quot;')

def make_safe_link(text, query, style=""):
    q = query.replace("\\", "\\\\")
    q = q.replace("'", "\\'")
    q = q.replace('"', '&quot;')
    return f'<a href="#" onclick="pycmd(\'browser:{q}\');return false;" style="{style}">{text}</a>'

def find_node(tree, target):
    if tree.deck_id == target:
        return tree
    for child in tree.children:
        n = find_node(child, target)
        if n: return n
    return None

def get_visual_counts(node, did):
    if not node.children:
        return node.new_count, node.learn_count, node.review_count
    
    total_new, total_lrn, total_due = 0, 0, 0
    for child in node.children:
        n, l, d = get_visual_counts(child, child.deck_id)
        total_new += n
        total_lrn += l
        total_due += d
        
    return max(total_new, node.new_count), max(total_lrn, node.learn_count), max(total_due, node.review_count)



def render_node(node, depth, cfg, is_pinned_root, idx, total_count, col_widths, parent_id=None):
    did = node.deck_id
    name = node.name.split("::")[-1]
    full_name = node.name
    full_name_esc = escape_for_html(full_name)
    
    new, lrn, due = get_visual_counts(node, did)
    has_kids = len(node.children) > 0
    expanded = did in cfg.get("expanded_ids", [])
    sym = "[-]" if expanded and has_kids else "[+]" if has_kids else ""
    expander = f'<span class="exp" onclick="pycmd(\'exp:{did}\');event.stopPropagation();">{sym}</span>' if has_kids else '<span class="expph"></span>'

    streak_thr = cfg.get("streak_threshold", 20)
    leech_thr = cfg.get("leech_threshold", 10)
    deck_goal = cfg.get("deck_goals", {}).get(str(did), 100)
    row_bg = cfg.get("deck_colors", {}).get(str(did), "")
    style_bg = f'style="background-color:{row_bg} !important;"' if row_bg else ""

    # Descompactando os 21 itens retornados
    maturity, retention, total_cards, tomorrow, done_today, speed, ease, leeches, mature_count_int, avg_time, _, total_stars, _, ease_counts, maturity_pct, retention_svg, reviews_svg, ease_svg, streak_qty_svg, streak_pct_svg, mature_cids_str = get_deck_stats_advanced(did, streak_thr, leech_thr, deck_goal)
    
    hp, xp, hp_pct = get_rpg_daily_stats(did)
    hp_color = "#5aff5a" if hp >= 70 else "#ff9d5a" if hp >= 30 else "#ff5a5a"
    hp_tooltip = f"{LANG.get('deck_hp', 'HP')}: {hp}/100"
    xp_display = f'<span title="{hp_tooltip}" style="cursor:help; font-size:9px; color:{"#FFD700" if xp>=0 else "#ff5a5a"}; margin-left:4px; font-weight:bold;">{"+" if xp>=0 else ""}{xp} XP</span>'
    
    hp_html = f'<div style="width: 100%; height: 6px; background: rgba(0,0,0,0.3); margin-top: 3px; border-radius: 3px; overflow: hidden; cursor: help;" title="{hp_tooltip}"><div style="width: {hp_pct}%; height: 100%; background: {hp_color}; transition: width 0.5s;"></div></div>'

    rpg_icon, rpg_title = get_rpg_icon(mature_count_int, total_cards)
    name_display = f'<span title="{rpg_title}" style="cursor:help; margin-right:4px;">{rpg_icon}</span>{name}'

    stars_html = f'<span title="{LANG.get("total_goals_hit_history", "Total")}: {total_stars}" style="color:#FFD700; font-size:10px; margin-left:2px; font-weight:bold;">⭐{total_stars}</span>' if total_stars > 0 else ""

    progress_html = ""
    if cfg.get("show_progress", True):
        remaining = new + lrn + due
        daily_total = done_today + remaining
        daily_pct = (done_today / daily_total * 100) if daily_total > 0 else (100 if done_today > 0 else 0)
        bar_color = "#FFD700" if (done_today >= deck_goal and deck_goal > 0) else ("#ff5a5a" if daily_pct < 50 else "#4da6ff" if daily_pct < 100 else "#5aff5a")
        tooltip_text = LANG.get("deck_progress_tooltip", "{pct}%").format(deck_name=full_name_esc, pct=int(daily_pct), done=done_today, total=daily_total) + f"&#10;🟥 {ease_counts[1]}   🟧 {ease_counts[2]}   🟩 {ease_counts[3]}   🟦 {ease_counts[4]}"
        progress_html = f'<div style="width: 100%; height: 6px; background: var(--progress-bg); margin-top: 2px; border-radius: 3px; overflow: hidden; cursor: help;" title="{tooltip_text}"><div style="width: {daily_pct}%; height: 100%; background: {bar_color}; transition: width 0.5s;"></div></div>'

    time_str = format_time_str(get_recursive_time_seconds(node)) if cfg.get("show_time", True) else "-"

    w_ord = col_widths.get("col_ord", 40)
    order_controls = '<td class="ord-col" style="position:relative; width:%dpx;" data-col="col_ord"></td>' % w_ord
    if is_pinned_root or parent_id is not None:
        parent_arg = f",{parent_id}" if parent_id else ""
        up_arrow = f'<a class="arr-btn" onclick="pycmd(\'move_up:{did}{parent_arg}\');return false;">▲</a>' if idx > 0 else '<span class="arr-ph"></span>'
        down_arrow = f'<a class="arr-btn" onclick="pycmd(\'move_down:{did}{parent_arg}\');return false;">▼</a>' if idx < total_count - 1 else '<span class="arr-ph"></span>'
        order_controls = f'<td class="ord-col" style="position:relative; width:{w_ord}px;" data-col="col_ord"><div class="ord-wrapper">{up_arrow}<input type="number" class="oi" value="{idx+1}" onchange="pycmd(\'ord:{did},{parent_arg},\'+this.value)">{down_arrow}</div><div class="resizer" onmousedown="rsStart(event, \'col_ord\')"></div></td>'

    drag_attrs = f'draggable="true" data-did="{did}" ondragstart="pdStart(event)" ondragover="pdOver(event)" ondragleave="pdLeave(event)" ondrop="pdDrop(event)"' if is_pinned_root else ""
    select_cell = f'<td class="sel-col" style="position:relative; width:{col_widths.get("col_select", 30)}px;" data-col="col_select"><input type="checkbox" class="study-cb" onclick="pycmd(\'select_deck:{did}\'); event.stopPropagation();" {"checked" if did in SELECTED_FOR_STUDY else ""} title="Selecionar para estudo em grupo"><div class="resizer" onmousedown="rsStart(event, \'col_select\')"></div></td>'

    def add_data_cell(key, content, css_class="inf", extra=""):
        if not cfg.get(key, True): return ""
        w = col_widths.get(key, 0)
        style = f'style="position:relative; {"width:"+str(w)+"px;" if w>0 else ""} {extra[7:-1] if extra.startswith("style=") else ""}"'
        return f'<td class="{css_class}" {style} {extra if not extra.startswith("style=") else ""} data-col="{key}">{content}<div class="resizer" onmousedown="rsStart(event, \'{key}\')"></div></td>'

    # CORREÇÃO DO LINK DE STREAK: Usando cid: com a lista de IDs
    streak_link = make_safe_link(maturity, f"cid:{mature_cids_str}") if (mature_count_int > 0 and mature_cids_str) else maturity

    data_map = {
        "show_time": (time_str, "inf", f'title="{LANG.get("estimated_time_tooltip", "Tempo")}"'),
        "show_avg_time": (avg_time, "inf", f'title="{LANG.get("avg_seconds_per_card", "Média")}"'),
        "show_speed": (speed, "inf", f'title="{LANG.get("speed_tooltip", "Velocidade")}"'),
        "show_goal": (f'<input type="number" value="{deck_goal}" onchange="pycmd(\'set_goal:{did},\'+this.value)" class="goal-input" title="Meta">{stars_html}', "inf", 'style="white-space:nowrap;"'),
        "show_retention": (retention, "inf", f'data-chart="{html_lib.escape(retention_svg)}" onmouseover="showMovingChart(this, event)" onmousemove="moveChart(event)" onmouseout="hideChart()"' if retention_svg else ""),
        "show_ease": (ease, "inf", f'data-chart="{html_lib.escape(ease_svg)}" onmouseover="showMovingChart(this, event)" onmousemove="moveChart(event)" onmouseout="hideChart()"' if ease_svg else ""),
        "show_leeches": (make_safe_link(leeches, f'deck:"{full_name}" prop:lapses>={leech_thr}', f'color:{"#ff5a5a" if leeches>0 else "var(--text-muted)"}') if leeches>0 else f'<span style="color:var(--text-muted)">{leeches}</span>', "inf", f'title="{LANG.get("leech_tooltip", "Sanguessugas").format(count=leech_thr)}"'),
        "show_tomorrow": (make_safe_link(tomorrow, f'deck:"{full_name}" prop:due=1', f'color:{"#ff9999" if tomorrow>50 else "var(--text-muted)"}') if tomorrow>0 else f'<span style="color:var(--text-muted)">{tomorrow}</span>', "inf", f'title="{LANG.get("tomorrow_tooltip", "Amanhã")}"'),
        "show_total": (total_cards, "inf", f'title="{LANG.get("total_tooltip", "Total")}"'),
        "show_streak_count": (streak_link, "mat", f'title="{LANG.get("streak_count_tooltip", "Streak").format(count=streak_thr)}"'),
        "show_streak_pct": (maturity_pct, "mat", f'title="{LANG.get("streak_pct_tooltip", "Streak %")}"')
    }

    cols_html = "".join(add_data_cell(k, *data_map[k]) for k in cfg.get("column_order", DEFAULT_COL_ORDER) if k in data_map)

    html = f'''
    <tr class="pr" {drag_attrs} {style_bg}>
        {order_controls} {select_cell}
        <td class="nm" style="padding-left:{depth*20}px; position:relative; width:{col_widths.get("col_name", 300)}px;" data-col="col_name">
            <div style="display:flex; align-items:center; overflow:hidden;">{expander}<a href="#" onclick="pycmd('open:{did}');return false;" title="{full_name_esc}" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{name_display}</a>{xp_display}</div>
            {hp_html} {progress_html} <div class="resizer" onmousedown="rsStart(event, 'col_name')"></div>
        </td>
        <td class="st" style="position:relative; width:{col_widths.get("col_counts", 160)}px;" data-col="col_counts" {f'data-chart="{html_lib.escape(reviews_svg)}" onmouseover="showMovingChart(this, event)" onmousemove="moveChart(event)" onmouseout="hideChart()"' if reviews_svg else ""}>
            <span class="n{'' if new else ' z'}">{new}</span><span class="l{' z' if not lrn else ''}">{lrn}</span><span class="d{' z' if not due else ''}">{due}</span>
            <div class="resizer" onmousedown="rsStart(event, 'col_counts')"></div>
        </td>
        {cols_html}
        <td class="op" style="position:relative; width:{col_widths.get("col_opts", 50)}px;" data-col="col_opts"><a href="#" onclick="pycmd('opts:{did}');return false;">⚙</a><div class="resizer" onmousedown="rsStart(event, 'col_opts')"></div></td>
    </tr>'''

    if has_kids and expanded:
        children = node.children
        saved_order = cfg.get("child_sort_order", {}).get(str(did), [])
        if saved_order:
            order_map = {int(id): i for i, id in enumerate(saved_order)}
            children.sort(key=lambda x: order_map.get(x.deck_id, 99999))
        for i, c in enumerate(children):
            html += render_node(c, depth+1, cfg, False, i, len(children), col_widths, parent_id=did)
    return html



def render_grid_node(node, depth, cfg, streak_thr, leech_thr):
    did = node.deck_id
    name = node.name.split("::")[-1]
    full_name = node.name
    full_name_esc = escape_for_html(full_name)
    
    new, lrn, due = get_visual_counts(node, did)
    
    has_kids = len(node.children) > 0
    expanded = did in cfg.get("expanded_ids", [])
    
    sym = "[-]" if expanded and has_kids else "[+]" if has_kids else ""
    expander = f'<span class="grid-exp" onclick="pycmd(\'exp:{did}\');event.stopPropagation();">{sym}</span>' if has_kids else ''

    deck_goal = cfg.get("deck_goals", {}).get(str(did), 100)
    row_bg = cfg.get("deck_colors", {}).get(str(did), "")
    
    cover_file = cfg.get("deck_covers", {}).get(str(did))
    cover_html = ""
    overlay_class = ""
    text_shadow_style = ""
    
    if cover_file:
        cover_html = f'<img src="{cover_file}" class="grid-cover"><div class="grid-overlay"></div>'
        text_shadow_style = 'text-shadow: 0 1px 3px rgba(0,0,0,0.9); color: #fff;'
    
    maturity, retention, total_cards, tomorrow, done_today, speed, ease, leeches, mature_count_int, avg_time, _, total_stars, _, ease_counts, maturity_pct, retention_svg, reviews_svg, ease_svg, streak_qty_svg, streak_pct_svg = get_deck_stats_advanced(did, streak_thr, leech_thr, deck_goal)
    rpg_icon, rpg_title = get_rpg_icon(mature_count_int, total_cards)
    
    hp, xp, hp_pct = get_rpg_daily_stats(did)
    xp_display = f'<span style="font-size:10px; color:#FFD700; font-weight:bold;">+{xp} XP</span>' if xp >= 0 else f'<span style="font-size:10px; color:#ff5a5a; font-weight:bold;">{xp} XP</span>'

    is_selected = did in SELECTED_FOR_STUDY
    checked_attr = "checked" if is_selected else ""
    select_checkbox = f'''
    <input type="checkbox" class="study-cb" onclick="pycmd('select_deck:{did}'); event.stopPropagation();" {checked_attr} title="Selecionar para estudo em grupo">
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
        
        progress_html = f'''
        <div class="grid-progress-bar" style="width: 100%; height: 4px; background: rgba(255,255,255,0.3); margin: 4px 0; border-radius: 2px; overflow: hidden; position: relative; z-index: 2;">
            <div style="width: {daily_pct}%; height: 100%; background: {bar_color};"></div>
        </div>
        '''

    time_str = format_time_str(get_recursive_time_seconds(node))
    
    leech_style = f'color:{"#ff5a5a" if leeches > 0 else "var(--text-muted)"}'
    if cover_file and leeches == 0: leech_style = "color: rgba(255,255,255,0.7);"
    
    if leeches > 0:
        query = f'deck:"{full_name}" prop:lapses>={leech_thr}'
        leech_content = make_safe_link(leeches, query, leech_style)
    else:
        leech_content = f'<span style="{leech_style}">{leeches}</span>'

    tom_style = f'color:{"#ff9999" if tomorrow > 50 else "var(--text-muted)"}'
    if cover_file and tomorrow <= 50: tom_style = "color: rgba(255,255,255,0.7);"

    if tomorrow > 0:
        query = f'deck:"{full_name}" prop:due=1'
        tom_content = make_safe_link(tomorrow, query, tom_style)
    else:
        tom_content = f'<span style="{tom_style}">{tomorrow}</span>'

    if mature_count_int > 0:
        query = f'deck:"{full_name}" prop:reps>={streak_thr}'
        streak_content = make_safe_link(maturity, query)
    else:
        streak_content = maturity

    tooltip_streak = LANG.get("mature_cards_count", "Streak").format(count=streak_thr)
    tooltip_leech = LANG.get("leeches_tooltip_long", "Sanguessugas").format(count=leech_thr)
    tooltip_streak_pct = LANG.get("mature_cards_pct", "Streak %")

    data_map = {
        "show_time": ("⏱️", time_str, LANG.get("estimated_time_tooltip", "Tempo")),
        "show_avg_time": ("s/card", avg_time, LANG.get("avg_seconds_per_card", "Média")),
        "show_speed": ("🚀", speed, LANG.get("speed_tooltip", "Velocidade")),
        "show_goal": ("🎯", f"{deck_goal}", LANG.get("daily_goal_tooltip", "Meta")),
        "show_retention": ("% Hj", retention, LANG.get("retention_rate_today", "Retenção")),
        "show_ease": ("⚖️", ease, LANG.get("avg_ease_tooltip", "Ease")),
        "show_leeches": ("🩸", leech_content, tooltip_leech),
        "show_tomorrow": ("🔮", tom_content, LANG.get("tomorrow_tooltip", "Amanhã")),
        "show_total": (LANG.get("total_tooltip", "Total"), total_cards, LANG.get("total_cards_in_deck", "Total")),

        "show_streak_count": (maturity, "mat", f'title="{tooltip_streak}"'),
        "show_streak_pct": (maturity_pct, "mat", f'title="{tooltip_streak_pct}"')
    }
    
    if mature_count_int > 0:
        data_map["show_streak_count"] = (streak_content, "mat", f'title="{tooltip_streak}"')

    grid_rows = ""
    col_order = cfg.get("column_order", DEFAULT_COL_ORDER)
    for key in col_order:
        if key in data_map and cfg.get(key, True):
            item = data_map[key]
            if key == "show_streak_count":
                icon = "🔥"
                val = streak_content
                tooltip = tooltip_streak
            elif key == "show_streak_pct":
                icon = "%🔥"
                val = maturity_pct
                tooltip = tooltip_streak_pct
            else:
                icon, val, tooltip = item

            grid_rows += f'<div class="grid-stat-row" title="{tooltip}" style="{text_shadow_style}"><span>{icon}</span><span>{val}</span></div>'

    bg_style = f'background-color:{row_bg};' if row_bg else 'background-color:var(--input-bg);'
    if cover_file: bg_style = 'background-color: #000;'
    
    border_color = ["#4da6ff", "#ff9999", "#5aff5a", "#FFD700", "#aa88ff"][depth % 5]
    depth_style = f'border-left: 3px solid {border_color};' if depth > 0 else ''

    html = f'''
    <div class="grid-item" style="{bg_style} {depth_style}" onclick="pycmd('open:{did}')" title="{full_name_esc} - {rpg_title}">
        {cover_html}
        <div class="grid-header" style="{text_shadow_style}">
            <div style="display:flex; align-items:center; gap:4px; overflow:hidden;">
                {expander}
                <span style="font-size:14px;">{rpg_icon}</span>
                <span class="grid-title">{name}</span>
            </div>
            <div style="display:flex; align-items:center; gap:5px;">
                {xp_display}
                {select_checkbox}
                <a href="#" onclick="pycmd('opts:{did}');event.stopPropagation();" class="grid-opt" style="{text_shadow_style}">⚙</a>
            </div>
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

    if has_kids and expanded:
        children = node.children
        saved_order = cfg.get("child_sort_order", {}).get(str(did), [])
        if saved_order:
            order_map = {int(id): i for i, id in enumerate(saved_order)}
            children.sort(key=lambda x: order_map.get(x.deck_id, 99999))
        
        for c in children:
            html += render_grid_node(c, depth+1, cfg, streak_thr, leech_thr)

    return html



def render_pinned(deck_browser, content):
    load_language()
    cfg = load_config()
    pinned = [d for d in cfg["pinned_ids"] if mw.col.decks.get(d)]

    if len(pinned) != len(cfg["pinned_ids"]):
        cfg["pinned_ids"] = pinned
        save_config(cfg)

    tree = mw.col.sched.deck_due_tree()
    collapsed = cfg.get("is_collapsed", False)
    hide_original = cfg.get("hide_original_list", False)
    is_grid = cfg.get("is_grid_view", False)
    streak_thr = cfg.get("streak_threshold", 20)
    leech_thr = cfg.get("leech_threshold", 10)
    chart_days = cfg.get("chart_days", 7)
    show_charts = cfg.get("show_charts", True)
    col_widths = cfg.get("col_widths", {})
    
    import re
    content.tree = re.sub(r'<a [^>]*class="(collapse|gears)"[^>]*>.*?</a>', '', content.tree, flags=re.DOTALL)
    content.tree = re.sub(r'^Decks(<br>)?', '', content.tree.strip())
    ghost_header = "<tr><th colspan='6' style='display:none;'></th></tr>"

    table_width_val = cfg.get("table_width", 98)
    if table_width_val is None: table_width_val = 98
    table_width_style = f"{table_width_val}%" if table_width_val <= 100 else f"{table_width_val}px"

    table_max_height = cfg.get("table_max_height", 400)
    if table_max_height is None: table_max_height = 400

    arrow = "▼" if not collapsed else "▶"
    disp = "none" if collapsed else ("flex" if is_grid else "table")
    eye_icon = "🐵" if not hide_original else "🙈"
    eye_title = LANG.get("hide_default_deck_list", "Ocultar") if not hide_original else LANG.get("show_default_deck_list", "Mostrar")
    grid_icon = "≡" if is_grid else "▦"
    grid_title = LANG.get("toggle_list_view", "Lista") if is_grid else LANG.get("toggle_grid_view", "Grade")

    study_button_html = ""
    if SELECTED_FOR_STUDY:
        count = len(SELECTED_FOR_STUDY)
        
        # --- INÍCIO DA MODIFICAÇÃO ---
        total_selected_cards = 0
        for did in SELECTED_FOR_STUDY:
            node = find_node(tree, did)
            if node:
                new, lrn, due = get_visual_counts(node, did)
                total_selected_cards += new + lrn + due
        
        button_text = f"{LANG.get('study_button', 'Estudar')} ({total_selected_cards})"
        button_title = LANG.get('study_selected_decks', 'Estudar {count} baralhos').format(count=count) + f" ({total_selected_cards} cards)"

        study_button_html = f'''
        <span class="pd-btn study-btn" onclick="pycmd('study_selected')" title="{button_title}">
            ▶️ {button_text}
        </span>
        '''
        # --- FIM DA MODIFICAÇÃO ---

    daily = get_daily_stats()
    last_review_time = get_last_review_time()
    label_time = LANG.get("last_review_time_label", "Horário da última rev:")
    
    global_streak = get_global_streak()
    label_streak = LANG.get("global_streak_label", "{day} dias seguidos").format(day=global_streak)

    checked_charts = "checked" if show_charts else ""
    tooltip_charts = LANG.get("show_hide_charts", "Mostrar/Ocultar Gráficos")
    
    chart_days_html = f'''
    <div style="display:flex; flex-direction:column; align-items:center; margin-right:10px;">
        <span style="font-size:9px; color:var(--text-muted);">{LANG.get('chart_days_label', 'Dias Gráfico')}</span>
        <div style="display:flex; align-items:center; gap:2px;">
            <input type="number" value="{chart_days}" onchange="pycmd('set_chart_days:'+this.value)" 
                   style="width:35px; text-align:center; background:var(--input-bg); color:var(--text-fg); border:1px solid var(--border); border-radius:3px; font-size:10px; padding:1px;">
            <input type="checkbox" {checked_charts} onchange="pycmd('toggle_charts')" 
                   style="cursor:pointer;" title="{tooltip_charts}">
        </div>
    </div>
    '''

    daily_html = f'''
    <div style="display:flex; flex-direction:column; align-items:flex-end; margin-right:15px;">
        <div style="font-size:10px; color:var(--text-muted); margin-bottom:1px; font-weight:bold;">
            {label_time} {last_review_time} <span style="color:#FFD700; margin-left:5px;">🔥 {label_streak}</span>
        </div>
        <div class="daily-stats" style="margin-right:0;" title="{LANG.get('today_answers', 'Hoje')}">
            <span style="color:#ff5a5a">■ {daily[1]}</span>
            <span style="color:#ff9d5a">■ {daily[2]}</span>
            <span style="color:#5aff5a">■ {daily[3]}</span>
            <span style="color:#5a9dff">■ {daily[4]}</span>
        </div>
    </div>
    '''

    rows = ""
    sum_new, sum_lrn, sum_due = 0, 0, 0
    total_seconds_global = 0
    total_tomorrow, total_leeches, total_streak, total_cards_global = 0, 0, 0, 0
    global_time_ms = 0
    global_reviews_today = 0
    global_passed_today = 0
    global_goal_sum = 0
    global_stars_sum = 0
    total_pinned_count = len(pinned)
    
    global_xp_sum = 0
    all_pinned_and_child_dids = set()

    for i, did in enumerate(pinned):
        node = find_node(tree, did)
        if node:
            n, l, d = get_visual_counts(node, did)
            sum_new += n
            sum_lrn += l
            sum_due += d
            
            if cfg.get("show_time", True):
                total_seconds_global += get_recursive_time_seconds(node)
            
            deck_goal = cfg.get("deck_goals", {}).get(str(did), 100)
            stats = get_deck_stats_advanced(did, streak_thr, leech_thr, deck_goal)
            
            all_pinned_and_child_dids.update(mw.col.decks.deck_and_child_ids(did))
            
            _, xp, _ = get_rpg_daily_stats(did)
            global_xp_sum += xp
            
            total_cards_global += stats[2]
            total_tomorrow += stats[3]
            total_leeches += stats[7]
            total_streak += stats[8]
            global_reviews_today += stats[4]
            global_time_ms += stats[10]
            global_stars_sum += stats[11]
            global_passed_today += stats[12]
            global_goal_sum += deck_goal
            
            if is_grid:
                rows += render_grid_node(node, 0, cfg, streak_thr, leech_thr)
            else:
                rows += render_node(node, 0, cfg, True, i, total_pinned_count, col_widths, parent_id=None)

    lvl_title, lvl_color, lvl_pct, global_pct, lvl_curr, lvl_max = get_global_rpg_level(global_xp_sum)
    
    lvl_pct_val = lvl_pct * 100
    global_pct_val = global_pct * 100
    
    if lvl_title == LANG.get("level_7_name", "LENDA"):
        tooltip_level = LANG.get("max_level_reached", "Max!")
    else:
        tooltip_level = f"{lvl_curr}/{lvl_max} {lvl_title} ({lvl_pct_val:.1f}%)"
        
    tooltip_global = f"{LANG.get('global_progress', 'Global')}: {global_xp_sum}/4000 ({global_pct_val:.1f}%)"
    
    global_chart_svg_escaped = ""
    if show_charts:
        global_daily_data = get_global_daily_summary(chart_days, dids=list(all_pinned_and_child_dids))
        
        if global_daily_data:
            today_date_str = global_daily_data[-1][0]
            global_daily_data[-1] = (today_date_str, global_reviews_today, global_xp_sum)

        processed_data_for_chart = []
        
        for date, cards, daily_xp in global_daily_data:
            level_title, _, _, _, _, _ = get_global_rpg_level(daily_xp)
            processed_data_for_chart.append((date, cards, daily_xp, level_title))
        
        global_chart_svg = generate_global_stats_svg(processed_data_for_chart)
        global_chart_svg_escaped = html_lib.escape(global_chart_svg)

    global_level_html = f'''
    <div id="global-level-container" 
         style="flex-grow:1; margin:0 15px; display:flex; flex-direction:column; justify-content:center;"
         onmouseover="showFixedChart(this, event)" onmouseout="hideChart()"
         data-chart="{global_chart_svg_escaped}">
        <div style="display:flex; justify-content:space-between; font-size:10px; color:var(--text-muted); margin-bottom:2px;">
            <span>{LANG.get("level", "Nvl")} {lvl_title}</span>
            <span>{global_xp_sum} XP</span>
        </div>
        <div title="{tooltip_level}" style="width:100%; height:4px; background:rgba(127,127,127,0.3); border-radius:2px; margin-bottom:2px; overflow:hidden; cursor:help;">
            <div style="width:{lvl_pct_val}%; height:100%; background:{lvl_color}; transition: width 0.5s;"></div>
        </div>
        <div title="{tooltip_global}" style="width:100%; height:4px; background:rgba(127,127,127,0.3); border-radius:2px; overflow:hidden; cursor:help;">
            <div style="width:{global_pct_val}%; height:100%; background:linear-gradient(90deg, #4da6ff, #aa88ff); transition: width 0.5s;"></div>
        </div>
    </div>
    '''

    current_sort = cfg.get("last_sort_col", "")
    is_desc = cfg.get("last_sort_desc", True)
    
    def get_sort_indicator(col_name):
        if current_sort == col_name:
            return " ▼" if is_desc else " ▲"
        return ""

    def add_col(key, title, tooltip, footer_val=""):
        if cfg.get(key, True):
            w = col_widths.get(key, 0)
            w_style = f"width:{w}px;" if w > 0 else ""
            
            move_controls = f'''
            <div class="col-move">
                <span onclick="pycmd('move_col:{key},left');event.stopPropagation();" title="{LANG.get('move_left', '<')}">&lt;</span>
                <span onclick="pycmd('move_col:{key},right');event.stopPropagation();" title="{LANG.get('move_right', '>')}">&gt;</span>
            </div>
            '''
            
            sort_arrow = get_sort_indicator(key)
            cursor_style = "cursor:pointer;"

            header_html = f'''
            <td class="col-header" title="{tooltip} ({LANG.get('click_to_sort', 'Ordenar')})" 
                onclick="pycmd('sort:{key}')"
                style="font-size:9px; text-align:center; color:var(--text-muted); vertical-align:bottom; position:relative; {w_style} {cursor_style}" 
                data-col="{key}">
                {move_controls}
                {title}{sort_arrow}
                <div class="resizer" onmousedown="rsStart(event, '{key}')"></div>
            </td>'''
            
            footer_html = f'<td style="text-align:center; color:var(--text-fg); font-size:11px;">{footer_val}</td>'
            return header_html, footer_html
        return "", ""

    avg_global_str = "-"
    if global_reviews_today > 0:
        avg_global = (global_time_ms / 1000) / global_reviews_today
        avg_global_str = f"{avg_global:.1f}s"
    
    global_speed_str = "-"
    if global_time_ms > 0:
        global_time_min = global_time_ms / 60000
        if global_time_min > 0:
            global_cpm = global_reviews_today / global_time_min
            global_speed_str = f"{global_cpm:.1f}"

    global_retention_str = "-"
    if global_reviews_today > 0:
        global_retention_str = f"{(global_passed_today / global_reviews_today) * 100:.0f}%"
    
    global_ease_str = "-"
    if pinned:
        all_pinned_ids_str = ",".join(str(d) for d in pinned)
        global_avg_ease = mw.col.db.scalar(f"SELECT avg(factor) FROM cards WHERE did IN ({all_pinned_ids_str}) AND queue != 0")
        if global_avg_ease:
            global_ease_str = f"{global_avg_ease/10:.0f}%"

    streak_footer_count = total_streak
    streak_footer_pct = "0%"
    if total_cards_global > 0:
        pct = (total_streak / total_cards_global) * 100
        streak_footer_pct = f"{pct:.0f}%"

    stars_footer = ""
    if global_stars_sum > 0:
        stars_footer = f'<span style="color:#FFD700; font-weight:bold; margin-left:2px;">⭐{global_stars_sum}</span>'

    total_time_footer = format_time_str(total_seconds_global)

    col_defs = {
        "show_time": ("⏱️", LANG.get("estimated_time_tooltip", "Tempo"), total_time_footer),
        "show_avg_time": ("s/card", LANG.get("avg_seconds_per_card", "Média"), avg_global_str),
        "show_speed": ("🚀", LANG.get("speed_tooltip", "Velocidade"), global_speed_str),
        "show_goal": ("🎯", LANG.get("daily_goal_reviews_tooltip", "Meta"), f"{global_goal_sum}{stars_footer}"),
        "show_retention": ("% Hj", LANG.get("retention_rate_today", "Retenção"), global_retention_str),
        "show_ease": ("⚖️", LANG.get("avg_ease_tooltip", "Ease"), global_ease_str),
        "show_leeches": (f'''🩸<br><input type="number" value="{leech_thr}" onclick="event.stopPropagation()" onchange="pycmd('set_leech:'+this.value)" style="width:35px; text-align:center; background:var(--input-bg); color:var(--text-fg); border:1px solid var(--border); border-radius:3px; font-size:10px; padding:1px;">''', 
                         LANG.get("leeches_tooltip_long", "Sanguessugas"), 
                         f"{total_leeches if total_leeches > 0 else ''}"),
        "show_tomorrow": ("🔮", LANG.get("cards_scheduled_for_tomorrow", "Amanhã"), total_tomorrow),
        "show_total": (LANG.get("total_tooltip", "Total"), LANG.get("total_cards_in_deck", "Total"), total_cards_global),
        "show_streak_count": (f'''Streak<br><input type="number" value="{streak_thr}" onclick="event.stopPropagation()" onchange="pycmd('set_streak:'+this.value)" style="width:35px; text-align:center; background:var(--input-bg); color:var(--text-fg); border:1px solid var(--border); border-radius:3px; font-size:10px; padding:1px;">''', 
                        LANG.get("mature_cards_count", "Streak"), 
                        streak_footer_count),
        "show_streak_pct": ("Streak %", LANG.get("mature_cards_pct", "Streak %"), streak_footer_pct)
    }

    header_cols = ""
    footer_cols = ""
    
    col_order = cfg.get("column_order", DEFAULT_COL_ORDER)
    
    for key in col_order:
        if key in col_defs:
            title, tooltip, foot_val = col_defs[key]
            h, f = add_col(key, title, tooltip, foot_val)
            header_cols += h
            footer_cols += f

    total_cols_count = 5 + sum(1 for k in col_defs.keys() if cfg.get(k, True))

    w_nm = col_widths.get("col_name", 300)
    style_nm = f"width:{w_nm}px;"
    w_st = col_widths.get("col_counts", 160)
    style_st = f"width:{w_st}px;"
    w_op = col_widths.get("col_opts", 50)
    style_op = f"width:{w_op}px;"
    w_ord = col_widths.get("col_ord", 40)
    style_ord = f"width:{w_ord}px;"
    w_sel = col_widths.get("col_select", 30)
    style_sel = f"width:{w_sel}px;"

    if not is_grid:
        if rows: 
            arrow_nm = get_sort_indicator("col_name")
            arrow_st = get_sort_indicator("col_counts")

            header_html = f'''
            <tr style="font-size:10px; color:var(--text-muted); line-height:1;">
                <td class="col-header" style="position:relative; {style_ord}" data-col="col_ord">
                    <div class="resizer-left" onmousedown="rsStartContainer(event, 'left')"></div>
                    <div class="resizer" onmousedown="rsStart(event, 'col_ord')"></div>
                </td>
                
                <td class="col-header" style="position:relative; {style_sel}; text-align:center;" data-col="col_select">
                    <div class="resizer" onmousedown="rsStart(event, 'col_select')"></div>
                </td>
                
                <td class="col-header" onclick="pycmd('sort:col_name')" title="{LANG.get('sort_by_name', 'Nome')}"
                    style="position:relative; cursor:pointer; {style_nm}" data-col="col_name">
                    {arrow_nm}
                    <div class="resizer" onmousedown="rsStart(event, 'col_name')"></div>
                </td>
                
                <td class="st col-header" onclick="pycmd('sort:col_counts')" title="{LANG.get('sort_by_count', 'Contagem')}"
                    style="padding-bottom:2px; vertical-align:bottom; position:relative; cursor:pointer; {style_st}" data-col="col_counts">
                    <span class="n" style="color:#7cf; font-weight:bold;">{LANG.get("new", "Novos")}</span>
                    <span class="l" style="color:#f99; font-weight:bold;">{LANG.get("learn", "Apr.")}</span>
                    <span class="d" style="color:#4CAF50; font-weight:bold;">{LANG.get("review", "Rev.")}</span>{arrow_st}
                    <div class="resizer" onmousedown="rsStart(event, 'col_counts')"></div>
                </td>
                {header_cols}
                <td class="col-header" style="position:relative; {style_op}" data-col="col_opts">
                    <div class="resizer" onmousedown="rsStart(event, 'col_opts')"></div>
                    <div class="resize-handle-right" onmousedown="rsStartContainer(event, 'right')"></div>
                </td>
            </tr>
            <tr style="background:rgba(127,127,127,0.1); border-bottom:1px solid var(--border); font-weight:bold;">
                <td></td>
                <td></td>
                <td class="nm" style="text-align:right; padding-right:10px; color:var(--text-fg); font-style:italic;">{LANG.get("totals", "Totais")}</td>
                <td class="st">
                    <span class="n">{sum_new}</span>
                    <span class="l">{sum_lrn}</span>
                    <span class="d">{sum_due}</span>
                </td>
                {footer_cols}
                <td></td>
            </tr>
            '''
            rows = header_html + rows
        else:
            rows = f'<tr><td colspan="{total_cols_count}" style="text-align:center;padding:20px;color:var(--text-muted)">{LANG.get("no_pinned_decks", "Vazio")}</td></tr>'
    else:
        if not rows:
            rows = f'<div style="text-align:center;padding:20px;color:var(--text-muted);width:100%;">{LANG.get("no_pinned_decks", "Vazio")}</div>'

    flag_br_b64 = image_to_base64("_user_files/br.jpg")
    flag_us_b64 = image_to_base64("_user_files/us.jpg")

    current_lang = cfg.get("language", "pt")
    active_class_pt = 'class="active"' if current_lang == 'pt' else ''
    active_class_en = 'class="active"' if current_lang == 'en' else ''

    lang_selector_html = f'''
    <div class="lang-selector">
        <a href="#" onclick="pycmd('set_lang:pt')"><img src="{flag_br_b64}" {active_class_pt} title="{LANG.get('lang_pt', 'PT')}"></a>
        <a href="#" onclick="pycmd('set_lang:en')"><img src="{flag_us_b64}" {active_class_en} title="{LANG.get('lang_en', 'EN')}"></a>
    </div>
    '''

    extra = f"""
    <style>
        .pdb-outer {{ display: flex; justify-content: center; width: 100%; }}
        .pdb {{
            --bg: #ffffff; --text-fg: #000000; --text-muted: #888888; --border: #cccccc;
            --header-bg: #e0e0e0; --input-bg: #ffffff; --progress-bg: #dddddd;
        }}
        .night .pdb {{
            --bg: #333333; --text-fg: #ffffff; --text-muted: #aaaaaa; --border: #555555;
            --header-bg: #444444; --input-bg: #222222; --progress-bg: #444444;
        }}
        .night .n:not(.z), .night .l:not(.z), .night .d:not(.z) {{
            color: white !important; border-radius: 4px; padding: 1px 0; font-weight: bold; background-color: #555;
        }}
        .night .n:not(.z) {{ background-color: #0277BD; }}
        .night .l:not(.z) {{ background-color: #D32F2F; }}
        .night .d:not(.z) {{ background-color: #388E3C; }}
        .pdb {{ 
            background: var(--bg); color: var(--text-fg); border: 1px solid var(--border); 
            border-radius: 8px; margin-bottom: 16px; overflow: hidden; box-sizing: border-box; 
            overflow-x: auto; overflow-y: auto; position: relative;
            width: {table_width_style}; max-width: 100%; max-height: {table_max_height}px;
            flex: 0 0 auto;
        }}
        .pdh {{ 
            background: var(--header-bg); color: var(--text-fg); padding: 8px 14px; font-weight: bold; 
            cursor: pointer; display: flex; justify-content: space-between; align-items: center; 
            user-select: none; border-bottom: 1px solid var(--border); 
            position: sticky; top: 0; z-index: 100;
        }}
        .pdb a {{ color: var(--text-fg) !important; text-decoration: none; }}
        .pdb a:hover {{ text-decoration: underline; opacity: 0.8; }}
        .pd-controls {{display:flex; gap:15px; align-items:center;}}
        .pd-btn {{cursor:pointer; font-size:18px; opacity:0.7; transition:opacity 0.2s;}}
        .pd-btn:hover {{opacity:1; transform:scale(1.1);}}
        .daily-stats {{ font-size: 12px; font-weight: normal; background:rgba(127,127,127,0.2); padding:2px 8px; border-radius:4px; }}
        .daily-stats span {{ margin-left: 6px; }}
        .daily-stats span:first-child {{ margin-left: 0; }}
        .lang-selector {{ display: flex; align-items: center; gap: 8px; margin-right: 15px; }}
        .lang-selector img {{ width: 24px; height: 16px; border-radius: 2px; border: 1px solid var(--border); cursor: pointer; opacity: 0.7; box-sizing: border-box; }}
        .lang-selector img:hover {{ opacity: 1; transform: scale(1.1); }}
        .lang-selector img.active {{
            border: 2px solid #4da6ff;
            opacity: 1;
        }}
        .pdb table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
        .grid-container {{ display: flex; flex-wrap: wrap; gap: 10px; padding: 10px; justify-content: flex-start; }}
        .grid-item {{ background: var(--input-bg); border: 1px solid var(--border); border-radius: 6px; padding: 8px; width: 160px; cursor: pointer; display: flex; flex-direction: column; gap: 5px; transition: transform 0.1s, box-shadow 0.1s; position: relative; overflow: hidden; }}
        .grid-item:hover {{ transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.2); }}
        .grid-header {{ display: flex; justify-content: space-between; align-items: center; font-weight: bold; font-size: 12px; border-bottom: 1px solid var(--border); padding-bottom: 4px; margin-bottom: 2px; }}
        .grid-title {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-grow: 1; margin: 0 4px; }}
        .grid-opt {{ font-size: 12px; opacity: 0.5; }}
        .grid-opt:hover {{ opacity: 1; }}
        .grid-counts {{ display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px; }}
        .grid-details {{ display: flex; flex-direction: column; gap: 2px; }}
        .grid-stat-row {{ display: flex; justify-content: space-between; font-size: 10px; color: var(--text-muted); border-bottom: 1px solid rgba(127,127,127,0.1); padding: 1px 0; }}
        .grid-exp {{ cursor: pointer; color: #4da6ff; font-weight: bold; margin-right: 2px; }}
        tr.pr {{ transition: filter 0.1s; }}
        tr.pr:hover {{ filter: brightness(0.92); }}
        .night tr.pr:hover {{ filter: brightness(1.15); }}
        tr.pr:hover > td {{ background-color: transparent !important; }}
        tr.pr[data-did]{{cursor:grab}}
        tr.pr.drag{{opacity:0.4; background:var(--header-bg) !important;}}
        tr.pr.over{{ border-top: 3px solid #ff6f00 !important; background: rgba(255, 111, 0, 0.2) !important; }}
        .exp{{cursor:pointer; color:#4da6ff; margin-right:6px; font-weight:bold}}
        .expph{{display:inline-block; width:16px}}
        td.st {{ white-space: nowrap; text-align: right; padding-right: 10px; }}
        .n, .l, .d, .z {{ display: inline-block; width: 45px; text-align: right; margin-left: 5px; }}
        .n{{color:#7cf}} .l{{color:#f99}} .d{{color:#4CAF50}} .z{{color:var(--text-muted)}}
        td.mat {{ width: 75px; text-align: center; color: var(--text-muted); font-size: 11px; white-space: nowrap; }}
        td.inf {{ width: 35px; text-align: center; color: var(--text-muted); font-size: 11px; }}
        input[type=number]::-webkit-inner-spin-button, input[type=number]::-webkit-outer-spin-button {{ -webkit-appearance: none; margin: 0; }}
        .ord-col {{ width: 60px; text-align: center; vertical-align: middle; }}
        .ord-wrapper {{ display: flex; align-items: center; justify-content: center; gap: 3px; }}
        .arr-btn {{ cursor: pointer; color: var(--text-muted); font-size: 12px; display: inline-block; padding: 0 4px; }}
        .arr-btn:hover {{ color: var(--text-fg); background: rgba(127,127,127,0.2); border-radius: 2px; }}
        .arr-ph {{ display: inline-block; width: 12px; }}
        .oi {{ width: 24px; text-align: center; border: 1px solid var(--border); background: var(--input-bg); color: var(--text-fg); border-radius: 3px; font-size: 10px; margin: 0; padding: 1px 0; }}
        .goal-input {{ width: 30px; text-align: center; border: 1px solid var(--border); background: var(--input-bg); color: var(--text-fg); border-radius: 3px; font-size: 10px; margin: 0; padding: 1px 0; }}
        .col-move {{ display: none; position: absolute; top: 0; left: 0; width: 100%; text-align: center; font-size: 9px; background: rgba(0,0,0,0.5); color: white; z-index: 25; }}
        .col-header:hover .col-move {{ display: block; }}
        .col-move span {{ cursor: pointer; padding: 0 4px; font-weight: bold; }}
        .col-move span:hover {{ color: #4da6ff; }}
        .resizer {{ position: absolute; top: 0; right: 0; width: 6px; cursor: col-resize; user-select: none; height: 100%; z-index: 20; border-right: 1px solid var(--border); }}
        .resizer:hover {{ background: rgba(127, 127, 127, 0.3); border-right: 2px solid #4da6ff; }}
        .resize-handle-left, .resize-handle-right {{ position: absolute; top: 0; bottom: 0; width: 12px; cursor: ew-resize; z-index: 50; }}
        .resize-handle-left {{ left: 0; }}
        .resize-handle-right {{ right: 0; }}
        .resize-handle-left:hover, .resize-handle-right:hover {{ background: rgba(77, 166, 255, 0.3); }}
        .resize-handle-bottom {{ position: absolute; left: 0; right: 0; bottom: 0; height: 12px; cursor: ns-resize; z-index: 60; }}
        .resize-handle-bottom:hover {{ background: rgba(77, 166, 255, 0.3); }}
        .resize-handle-top {{ position: absolute; left: 0; right: 0; top: 0; height: 10px; cursor: ns-resize; z-index: 110; }}
        .resize-handle-top:hover {{ background: rgba(77, 166, 255, 0.3); }}
        .col-header {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .pdb td {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .pd-btn.study-btn {{
            font-size: 14px;
            font-weight: bold;
            color: #5aff5a;
            background: rgba(90, 255, 90, 0.15);
            padding: 3px 10px;
            border-radius: 5px;
            border: 1px solid rgba(90, 255, 90, 0.3);
        }}
        .pd-btn.study-btn:hover {{
            color: #fff;
            background: #5aff5a;
            transform: scale(1.05);
        }}
        .sel-col {{
            text-align: center;
            vertical-align: middle;
        }}
        .study-cb {{
            cursor: pointer;
            width: 16px;
            height: 16px;
            vertical-align: middle;
        }}
        #chart-tooltip {{
            position: fixed;
            display: none;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 4px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 99999;
            padding: 5px;
            max-width: 620px;
        }}
    </style>
    <div id="chart-tooltip"></div>
    <script>
        var srcDid = null;
        window.pdStart = function(e){{ if(e.target.tagName === "INPUT") return; var tr = e.target.closest("tr[data-did]"); if(!tr) return; srcDid = tr.dataset.did; tr.classList.add("drag"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", srcDid); }};
        window.pdOver = function(e){{ e.preventDefault(); var tr = e.target.closest("tr[data-did]"); if(tr && tr.dataset.did !== srcDid) tr.classList.add("over"); }};
        window.pdLeave = function(e){{ var tr = e.target.closest("tr[data-did]"); if(tr) tr.classList.remove("over"); }};
        window.pdDrop = function(e){{ e.preventDefault(); e.stopPropagation(); document.querySelectorAll("tr.pr").forEach(r=>r.classList.remove("over", "drag")); var targetTr = e.target.closest("tr[data-did]"); var targetDid = targetTr ? targetTr.dataset.did : null; var droppedDid = e.dataTransfer.getData("text/plain") || e.dataTransfer.getData("anki-did") || srcDid; if(!droppedDid) return; if(targetDid && droppedDid !== targetDid) pycmd("insert_at:" + droppedDid + "," + targetDid); else if (!targetDid) pycmd("pin_end:" + droppedDid); srcDid = null; }};
        window.pdBoxDrop = function(e){{ e.preventDefault(); var droppedDid = e.dataTransfer.getData("anki-did") || srcDid; if(droppedDid) pycmd("pin_end:" + droppedDid); }};
        new MutationObserver(()=>{{ document.querySelectorAll('tr[id^="did"]:not([data-pd])').forEach(r=>{{ r.dataset.pd = "1"; r.draggable = true; r.ondragstart = e => {{ e.dataTransfer.setData("anki-did", r.id.slice(3)); }}; }}); }}).observe(document.body, {{childList:true, subtree:true}});
        var rsCol = null, rsStartX = 0, rsStartW = 0;
        window.rsStart = function(e, colName) {{ e.preventDefault(); e.stopPropagation(); rsCol = colName; rsStartX = e.pageX; var td = e.target.closest("td"); rsStartW = td.offsetWidth; document.addEventListener("mousemove", rsMove); document.addEventListener("mouseup", rsUp); document.body.style.cursor = "col-resize"; }};
        function rsMove(e) {{ if(!rsCol) return; var diff = e.pageX - rsStartX; var newW = rsStartW + diff; if(newW < 20) newW = 20; var tds = document.querySelectorAll('td[data-col="'+rsCol+'"]'); tds.forEach(function(td){{ td.style.width = newW + "px"; }}); }}
        function rsUp(e) {{ document.removeEventListener("mousemove", rsMove); document.removeEventListener("mouseup", rsUp); document.body.style.cursor = "default"; if(rsCol) {{ var diff = e.pageX - rsStartX; var newW = rsStartW + diff; if(newW < 20) newW = 20; pycmd("resize:" + rsCol + "," + newW); }} rsCol = null; }}
        var rsContStartVal = 0, rsContStartX = 0, rsContStartY = 0, rsContSide = null;
        window.rsStartContainer = function(e, side) {{ e.preventDefault(); e.stopPropagation(); rsContSide = side; rsContStartX = e.pageX; rsContStartY = e.pageY; var pdb = document.querySelector('.pdb'); if (side === 'left' || side === 'right') {{ rsContStartVal = pdb.offsetWidth; document.body.style.cursor = "ew-resize"; }} else if (side === 'bottom' || side === 'top') {{ rsContStartVal = pdb.offsetHeight; document.body.style.cursor = "ns-resize"; }} document.addEventListener("mousemove", rsMoveContainer); document.addEventListener("mouseup", rsUpContainer); }};
        function rsMoveContainer(e) {{ if(!rsContSide) return; if (rsContSide === 'right') {{ var diff = e.pageX - rsContStartX; var newW = rsContStartVal + diff; if(newW < 400) newW = 400; document.querySelector('.pdb').style.width = newW + "px"; }} else if (rsContSide === 'left') {{ var diff = e.pageX - rsContStartX; var newW = rsContStartVal - diff; if(newW < 400) newW = 400; document.querySelector('.pdb').style.width = newW + "px"; }} else if (rsContSide === 'bottom') {{ var diff = e.pageY - rsContStartY; var newH = rsContStartVal + diff; if(newH < 100) newH = 100; document.querySelector('.pdb').style.maxHeight = newH + "px"; }} else if (rsContSide === 'top') {{ var diff = e.pageY - rsContStartY; var newH = rsContStartVal - diff; if(newH < 100) newH = 100; document.querySelector('.pdb').style.maxHeight = newH + "px"; }} }}
        function rsUpContainer(e) {{ document.removeEventListener("mousemove", rsMoveContainer); document.removeEventListener("mouseup", rsUpContainer); document.body.style.cursor = "default"; if(rsContSide) {{ var pdb = document.querySelector('.pdb'); if (rsContSide === 'left' || rsContSide === 'right') {{ pycmd("resize_container:" + pdb.offsetWidth); }} else if (rsContSide === 'bottom' || rsContSide === 'top') {{ pycmd("resize_height:" + pdb.offsetHeight); }} }} rsContSide = null; }}
        
        var chartTooltip = document.getElementById('chart-tooltip');
        var hideChartTimer;
        
        window.showFixedChart = function(el, event) {{
            clearTimeout(hideChartTimer);
            var svgContent = el.dataset.chart;
            if (!svgContent) return;
            chartTooltip.innerHTML = svgContent;
            chartTooltip.style.display = 'block';
            chartTooltip.style.pointerEvents = 'auto';
            moveChart(event);
        }};

        window.showMovingChart = function(el, event) {{
            clearTimeout(hideChartTimer);
            var svgContent = el.dataset.chart;
            if (!svgContent) return;
            chartTooltip.innerHTML = svgContent;
            chartTooltip.style.display = 'block';
            chartTooltip.style.pointerEvents = 'none';
            moveChart(event);
        }};

        window.moveChart = function(e) {{
            if (!e || chartTooltip.style.display !== 'block') return;
            var tooltipWidth = chartTooltip.offsetWidth;
            var tooltipHeight = chartTooltip.offsetHeight;
            var x = e.clientX + 15;
            var y = e.clientY + 15;
            if (x + tooltipWidth > window.innerWidth) {{
                x = e.clientX - tooltipWidth - 15;
            }}
            if (y + tooltipHeight > window.innerHeight) {{
                y = e.clientY - tooltipHeight - 15;
            }}
            chartTooltip.style.left = x + 'px';
            chartTooltip.style.top = y + 'px';
        }};

        window.hideChart = function() {{
            hideChartTimer = setTimeout(function() {{
                chartTooltip.style.display = 'none';
            }}, 300);
        }};

        chartTooltip.addEventListener('mouseover', function() {{ clearTimeout(hideChartTimer); }});
        chartTooltip.addEventListener('mouseout', function() {{ hideChart(); }});
    </script>
    """

    theme_class = "night" if theme_manager.night_mode else ""
    
    content_html = ""
    if is_grid:
        content_html = f'<div class="grid-container">{rows}</div>'
    else:
        content_html = f'<table style="display:{disp};">{rows}</table>'

    pinned_html = f'''
    {extra}
    <tr class="pd-wrapper-row">
        <td colspan="20" style="padding:0; border:none;">
            <div class="{theme_class}">
                <div class="pdb-outer">
                    <div class="pdb" ondragover="event.preventDefault()" ondrop="pdBoxDrop(event)">
                        <div class="resize-handle-top" onmousedown="rsStartContainer(event, 'top')"></div>
                        <div class="resize-handle-left" onmousedown="rsStartContainer(event, 'left')"></div>
                        <div class="pdh">
                            <div onclick="pycmd('colap')" style="flex-grow:0; white-space:nowrap; margin-right:10px;">{LANG.get("pinned_decks_title", "Decks Fixados")} ({len(pinned)})</div>
                            {global_level_html}
                            <div class="pd-controls">
                                {lang_selector_html}
                                {chart_days_html}
                                {daily_html}
                                {study_button_html}
                                <span class="pd-btn" onclick="pycmd('toggle_grid')" title="{grid_title}">{grid_icon}</span>
                                <span class="pd-btn" onclick="pycmd('export_html')" title="{LANG.get('generate_html_report', 'Relatório')}">📄</span>
                                <span class="pd-btn" onclick="pycmd('toggle_original')" title="{eye_title}">{eye_icon}</span>
                                <span class="pd-btn" onclick="pycmd('colap')">{arrow}</span>
                            </div>
                        </div>
                        {content_html}
                        <div class="resize-handle-right" onmousedown="rsStartContainer(event, 'right')"></div>
                        <div class="resize-handle-bottom" onmousedown="rsStartContainer(event, 'bottom')"></div>
                    </div>
                </div>
            </div>
        </td>
    </tr>
    '''

    if hide_original:
        content.tree = ghost_header + pinned_html
    else:
        content.tree = ghost_header + pinned_html + content.tree



# ==================== COMANDOS ====================

def update_child_order(c, parent_id, child_list):
    if "child_sort_order" not in c:
        c["child_sort_order"] = {}
    c["child_sort_order"][str(parent_id)] = child_list
    save_config(c)

def get_children_order(c, parent_id):
    saved = c.get("child_sort_order", {}).get(str(parent_id), [])
    if saved: return saved
    tree = mw.col.sched.deck_due_tree()
    node = find_node(tree, parent_id)
    if node:
        return [child.deck_id for child in node.children]
    return []

def export_html_report():
    cfg = load_config()
    pinned = [d for d in cfg["pinned_ids"] if mw.col.decks.get(d)]
    tree = mw.col.sched.deck_due_tree()
    
    streak_thr = cfg.get("streak_threshold", 20)
    leech_thr = cfg.get("leech_threshold", 10)
    
    rows_data = []
    
    totals = {
        "new": 0, "lrn": 0, "due": 0,
        "time_ms": 0, "reviews": 0, "passed": 0,
        "streak": 0, "cards": 0, "stars": 0,
        "goal": 0, "leeches": 0, "tomorrow": 0,
        "xp": 0, "time_seconds": 0
    }

    def process_node(node, depth):
        did = node.deck_id
        
        new, lrn, due = get_visual_counts(node, did)
        
        deck_goal = cfg.get("deck_goals", {}).get(str(did), 100)
        stats = get_deck_stats_advanced(did, streak_thr, leech_thr, deck_goal)
        
        rpg = get_rpg_daily_stats(did)
        
        rec_seconds = get_recursive_time_seconds(node)

        if depth == 0:
            totals["new"] += new
            totals["lrn"] += lrn
            totals["due"] += due
            totals["cards"] += stats[2]
            totals["tomorrow"] += stats[3]
            totals["reviews"] += stats[4]
            totals["leeches"] += stats[7]
            totals["streak"] += stats[8]
            totals["time_ms"] += stats[10]
            totals["stars"] += stats[11]
            totals["passed"] += stats[12]
            totals["goal"] += deck_goal
            totals["xp"] += rpg[1]
            totals["time_seconds"] += rec_seconds

        row = {
            "name": node.name.split("::")[-1],
            "full_name": node.name,
            "did": did,
            "depth": depth,
            "counts": (new, lrn, due),
            "stats": stats[:15],
            "rpg": rpg,
            "goal": deck_goal,
            "bg_color": cfg.get("deck_colors", {}).get(str(did), ""),
            "has_children": len(node.children) > 0,
            "expanded": did in cfg.get("expanded_ids", []),
            "recursive_seconds": rec_seconds,
            "ease_counts": stats[13]
        }
        rows_data.append(row)
        
        if len(node.children) > 0 and did in cfg.get("expanded_ids", []):
            children = node.children
            saved_order = cfg.get("child_sort_order", {}).get(str(did), [])
            if saved_order:
                order_map = {int(id): i for i, id in enumerate(saved_order)}
                children.sort(key=lambda x: order_map.get(x.deck_id, 99999))
            
            for child in children:
                process_node(child, depth + 1)

    for did in pinned:
        node = find_node(tree, did)
        if node:
            process_node(node, 0)

    daily_stats = get_daily_stats()
    last_rev = get_last_review_time()
    glob_streak = get_global_streak()
    
    html_content = report_html.generate_report(
        rows_data, totals, daily_stats, cfg, 
        theme_manager.night_mode, mw.col.media.dir(), 
        LANG, last_rev, glob_streak
    )
    
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tf:
            tf.write(html_content)
            tf_path = tf.name
        
        webbrowser.open(f"file:///{tf_path}")
        tooltip(LANG.get("html_report_generated", "Relatório gerado!"))
    except Exception as e:
        tooltip(f"Erro ao gerar HTML: {e}")

def handler(cmd):
    if cmd == "colap":
        c = load_config()
        c["is_collapsed"] = not c.get("is_collapsed", False)
        save_config(c)
        mw.deckBrowser.refresh()
    elif cmd == "toggle_original":
        c = load_config()
        c["hide_original_list"] = not c.get("hide_original_list", False)
        save_config(c)
        mw.deckBrowser.refresh()
    elif cmd.startswith("select_deck:"):
        try:
            did = int(cmd.split(":")[1])
            if did in SELECTED_FOR_STUDY:
                SELECTED_FOR_STUDY.remove(did)
            else:
                SELECTED_FOR_STUDY.add(did)
            mw.deckBrowser.refresh()
        except:
            pass
    elif cmd == "study_selected":
        start_custom_study_session()
    elif cmd == "toggle_grid":
        c = load_config()
        c["is_grid_view"] = not c.get("is_grid_view", False)
        save_config(c)
        mw.deckBrowser.refresh()
    elif cmd == "export_html":
        export_html_report()
    elif cmd.startswith("sort:"):
        col = cmd.split(":")[1]
        sort_pinned_decks(col)
    elif cmd.startswith("browser:"):
        query = cmd[8:]
        browser = dialogs.open("Browser", mw)
        browser.setFilter(query)
    elif cmd.startswith("set_lang:"):
        lang_code = cmd.split(":")[1]
        if lang_code in ["pt", "en"]:
            c = load_config()
            c["language"] = lang_code
            save_config(c)
            clear_stats_cache()
            mw.deckBrowser.refresh()
    elif cmd.startswith("resize_container:"):
        try:
            width = int(float(cmd.split(":")[1]))
            c = load_config()
            c["table_width"] = width
            save_config(c)
        except: pass
    elif cmd.startswith("resize_height:"):
        try:
            height = int(float(cmd.split(":")[1]))
            c = load_config()
            c["table_max_height"] = height
            save_config(c)
        except: pass
    elif cmd.startswith("resize:"):
        try:
            parts = cmd[7:].split(",")
            col_name = parts[0]
            width = int(float(parts[1]))
            c = load_config()
            if "col_widths" not in c: c["col_widths"] = {}
            c["col_widths"][col_name] = width
            save_config(c)
        except Exception as e:
            print("Erro resize:", e)
    elif cmd.startswith("move_col:"):
        try:
            parts = cmd[9:].split(",")
            key = parts[0]
            direction = parts[1]
            c = load_config()
            order = c.get("column_order", DEFAULT_COL_ORDER)
            
            if key in order:
                idx = order.index(key)
                if direction == "left" and idx > 0:
                    order[idx], order[idx-1] = order[idx-1], order[idx]
                elif direction == "right" and idx < len(order) - 1:
                    order[idx], order[idx+1] = order[idx+1], order[idx]
                
                c["column_order"] = order
                save_config(c)
                mw.deckBrowser.refresh()
        except Exception as e:
            print("Erro move_col:", e)
    elif cmd.startswith("exp:"):
        did = int(cmd[4:])
        c = load_config()
        ex = set(c.get("expanded_ids", []))
        ex.symmetric_difference_update([did])
        c["expanded_ids"] = list(ex)
        save_config(c)
        mw.deckBrowser.refresh()
    elif cmd.startswith("pin_end:"):
        did = int(cmd[8:])
        c = load_config()
        ids = c["pinned_ids"]
        if did not in ids:
            ids.append(did)
        c["pinned_ids"] = ids
        save_config(c)
        mw.deckBrowser.refresh()
    elif cmd.startswith("insert_at:"):
        try:
            src, tgt = map(int, cmd[10:].split(","))
            c = load_config()
            ids = c["pinned_ids"]
            if src in ids: ids.remove(src)
            if tgt in ids:
                idx = ids.index(tgt)
                ids.insert(idx, src)
            else:
                ids.append(src)
            c["pinned_ids"] = ids
            save_config(c)
            mw.deckBrowser.refresh()
        except: pass
    elif cmd.startswith("move_up:"):
        try:
            parts = cmd.split(":")[1].split(",")
            did = int(parts[0])
            parent_id = int(parts[1]) if len(parts) > 1 and parts[1] else None
            c = load_config()
            if parent_id:
                ids = get_children_order(c, parent_id)
                if did in ids:
                    idx = ids.index(did)
                    if idx > 0:
                        ids[idx], ids[idx-1] = ids[idx-1], ids[idx]
                        update_child_order(c, parent_id, ids)
                        mw.deckBrowser.refresh()
            else:
                ids = c["pinned_ids"]
                if did in ids:
                    idx = ids.index(did)
                    if idx > 0:
                        ids[idx], ids[idx-1] = ids[idx-1], ids[idx]
                        save_config(c)
                        mw.deckBrowser.refresh()
        except Exception as e: print(e)
    elif cmd.startswith("move_down:"):
        try:
            parts = cmd.split(":")[1].split(",")
            did = int(parts[0])
            parent_id = int(parts[1]) if len(parts) > 1 and parts[1] else None
            c = load_config()
            if parent_id:
                ids = get_children_order(c, parent_id)
                if did in ids:
                    idx = ids.index(did)
                    if idx < len(ids) - 1:
                        ids[idx], ids[idx+1] = ids[idx+1], ids[idx]
                        update_child_order(c, parent_id, ids)
                        mw.deckBrowser.refresh()
            else:
                ids = c["pinned_ids"]
                if did in ids:
                    idx = ids.index(did)
                    if idx < len(ids) - 1:
                        ids[idx], ids[idx+1] = ids[idx+1], ids[idx]
                        save_config(c)
                        mw.deckBrowser.refresh()
        except Exception as e: print(e)
    elif cmd.startswith("ord:"):
        try:
            parts = cmd[4:].split(",")
            did_movido = int(parts[0])
            parent_str = parts[1]
            parent_id = int(parent_str) if parent_str else None
            nova_posicao = int(parts[2])
            c = load_config()
            if parent_id:
                ids = get_children_order(c, parent_id)
                if did_movido in ids:
                    indice_atual = ids.index(did_movido)
                    indice_destino = max(0, min(nova_posicao - 1, len(ids) - 1))
                    ids[indice_atual], ids[indice_destino] = ids[indice_destino], ids[indice_atual]
                    update_child_order(c, parent_id, ids)
                    mw.deckBrowser.refresh()
            else:
                ids = c["pinned_ids"]
                if did_movido in ids:
                    indice_atual = ids.index(did_movido)
                    indice_destino = max(0, min(nova_posicao - 1, len(ids) - 1))
                    ids[indice_atual], ids[indice_destino] = ids[indice_destino], ids[indice_atual]
                    c["pinned_ids"] = ids
                    save_config(c)
                    mw.deckBrowser.refresh()
        except Exception as e:
            print(e)
    elif cmd.startswith("set_streak:"):
        try:
            val = int(cmd.split(":")[1])
            if val < 1: val = 1
            c = load_config()
            c["streak_threshold"] = val
            save_config(c)
            clear_stats_cache()
            mw.deckBrowser.refresh()
        except: pass
    elif cmd.startswith("set_leech:"):
        try:
            val = int(cmd.split(":")[1])
            if val < 1: val = 1
            c = load_config()
            c["leech_threshold"] = val
            save_config(c)
            clear_stats_cache()
            mw.deckBrowser.refresh()
        except: pass
    elif cmd.startswith("set_chart_days:"):
        try:
            val = int(cmd.split(":")[1])
            if val < 3: val = 3
            c = load_config()
            c["chart_days"] = val
            save_config(c)
            clear_stats_cache()
            mw.deckBrowser.refresh()
        except: pass
    elif cmd.startswith("toggle_charts"):
        c = load_config()
        c["show_charts"] = not c.get("show_charts", True)
        save_config(c)
        clear_stats_cache()
        mw.deckBrowser.refresh()
    elif cmd.startswith("set_goal:"):
        try:
            parts = cmd[9:].split(",")
            did = parts[0]
            val = int(parts[1])
            if val < 1: val = 1
            c = load_config()
            if "deck_goals" not in c: c["deck_goals"] = {}
            c["deck_goals"][did] = val
            save_config(c)
            clear_stats_cache()
            mw.deckBrowser.refresh()
        except: pass
    else:
        if hasattr(mw.deckBrowser, "_old_handler"):
            mw.deckBrowser._old_handler(cmd)

def on_review_answered(reviewer, card, ease):
    clear_stats_cache()


def cleanup_temp_deck_before_render(deck_browser, content):
    """
    Remove o deck temporário ANTES da tela de baralhos ser renderizada.
    Isso garante que as contagens dos baralhos originais sejam recalculadas corretamente.
    """
    try:
        did = mw.col.decks.id_for_name(TEMP_DECK_NAME)
        if did:
            # Remove o baralho temporário
            mw.col.decks.remove([did])
            
            # Força o agendador a resetar seu estado interno.
            # Como isso acontece ANTES da renderização, a árvore de baralhos
            # será construída com os dados corretos.
            mw.col.sched.reset()
    except Exception as e:
        # É uma boa prática registrar erros caso algo inesperado aconteça
        print(f"Pinned Decks: Error during temp deck cleanup: {e}")

gui_hooks.deck_browser_will_show_options_menu.append(on_options_menu)
gui_hooks.deck_browser_will_render_content.append(render_pinned)
gui_hooks.reviewer_did_answer_card.append(on_review_answered)

gui_hooks.deck_browser_will_render_content.append(cleanup_temp_deck_before_render)

if not hasattr(mw.deckBrowser, "_old_handler"):
    mw.deckBrowser._old_handler = mw.deckBrowser._linkHandler
mw.deckBrowser._linkHandler = lambda url: handler(url)
