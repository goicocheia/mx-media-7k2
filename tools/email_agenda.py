#!/usr/bin/env python3
"""E-mail diário da programação de posts da Meta.X (pedido do Márcio em 18/11/2026).

uso: python3 email_agenda.py DADOS_PY DIA [SAIDA_DIR] [--mes 11 --ano 2026]
  DADOS_PY: claude/scripts/calendario.py do Projeto, ou um recorte dele (dados.py) com as mesmas variáveis:
  FEED, STORIES, ROTULO, NOTAS e, se houver, CAPA {(dia, 'HH:MM'): 'arquivo.jpg'} e STORY_VIDEO {arte: 'arquivo.mp4'}
  DIA: dia do mês (ex.: 18)
Saída em SAIDA_DIR (padrão ./saida-email): agenda.jpg (imagem do e-mail), corpo.html (usa cid:att0),
corpo.txt, assunto.txt e lembretes.json (itens do feed do dia, para os lembretes do Outlook).
Miniaturas: capas públicas do GitHub Pages (mapa CAPA abaixo; peça nova sem capa vira um quadro com o título)
e, para stories, um quadro do próprio vídeo (st-MMDD-x.mp4). Precisa de curl, ffmpeg e playwright (Python).
"""
import os, sys, re, json, html, subprocess, datetime, pathlib, argparse
from playwright.sync_api import sync_playwright

BASE = 'https://goicocheia.github.io/mx-media-7k2/'
# capa pública de cada peça do feed: (dia, hora) -> arquivo no GitHub Pages. Ao agendar peça nova, acrescentar aqui.
CAPA = {
 (17, '11:31'): 'recusa-1.jpg', (17, '14:30'): 'governanca-1.jpg', (17, '14:32'): 'governanca-1.jpg', (17, '15:30'): 'reel-aftermovie-workshop-capa.jpg',
 (17, '15:32'): 'reel-aftermovie-workshop-capa.jpg', (17, '16:30'): 'reel-vozes-ep01-capa.jpg', (17, '17:30'): 'reel-projeto-cerrado-capa.jpg',
 (17, '17:32'): 'reel-projeto-cerrado-capa.jpg', (18, '11:31'): 'contratado-1.jpg',
 (18, '11:30'): 'contratado-1.jpg', (18, '14:30'): 'reel-reforma-tributaria-capa.jpg', (18, '17:30'): 'reel-parada-geral-capa.jpg',
 (18, '19:00'): 'reel-vozes-ep02-capa-escura.jpg', (18, '20:30'): 'reel-vozes-ep03-capa-v2.jpg',
 (19, '11:30'): 'decisao-1.jpg', (19, '14:30'): 'reel-vozes-ep04-capa.jpg', (19, '17:30'): 'reel-tres-lagoas-capa.jpg',
 (20, '11:30'): 'ia-erro-1.jpg', (20, '17:30'): 'reel-carajas-capa.jpg',
 (23, '11:30'): 'tecnologia-1.jpg', (23, '17:30'): 'reel-eucalipto-celulose-capa.jpg',
 (24, '11:30'): 'teste-1.jpg', (24, '17:30'): 'reel-tubarao-capa.jpg',
 (25, '11:30'): 'byd-1.jpg', (25, '14:30'): 'nr1-1.jpg', (25, '17:30'): 'reel-projeto-star-capa.jpg',
 (26, '11:30'): 'radar-terceiros-1.jpg', (26, '17:30'): 'reel-alunorte-capa.jpg',
 (27, '17:30'): 'reel-tecnico-de-seguranca-capa.jpg', (30, '17:30'): 'reel-pecem-capa.jpg',
}
# stories que não seguem o padrão st-MMDD-x: arte do calendário -> vídeo
STORY_VIDEO = {'img:98d51688cbb037f5b3f58c82c2be0bf3': 'st-workshop-diagnostico-bio.mp4',
               'img:e46ce14294ac32d33ce15d8e749c25c7': 'st-aftermovie-abertura.mp4'}
SEMANA = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']
MESES = ['', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
STATUS = {'pub': 'Publicado', 'ag': 'Agendado', 'pronto': 'Falta agendar', 'ok': 'Aguarda OK', 'criar': 'A criar', 'off': 'Não sai'}
REDE = {'IG': 'Instagram', 'LI': 'LinkedIn', '4 redes': 'Instagram, YouTube, TikTok e LinkedIn'}
esc = html.escape


def carrega(path):
    src = open(path, encoding='utf-8').read()
    corte = src.find('# ---------------------------------------------------------------- estilos')
    ns = {'__file__': os.path.abspath(path)}
    exec(compile(src[:corte] if corte > 0 else src, path, 'exec'), ns)
    return ns


def baixa(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return True
    r = subprocess.run(['curl', '-sfL', '--max-time', '60', '-o', dest, url])
    return r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0


def quadro_story(video, dest):
    tmp = dest + '.mp4'
    if not baixa(BASE + video, tmp):
        return False
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', '3', '-i', tmp, '-frames:v', '1', '-vf', 'scale=270:-2', '-q:v', '3', dest])
    return os.path.exists(dest)

# ---------------------------------------------------------------- análise do dia anterior (advisor)
# analise.json:
# {"data_ref": "17/11", "dia_semana": "terça", "manchete": "uma frase com o veredito",
#  "kpis": [{"rotulo": "Alcance do perfil", "valor": "35,6 mil", "delta": "+46% vs média de 7 dias", "tom": "bom|ruim|neutro"}],   (até 4)
#  "pecas": [{"hora": "17:32", "tipo": "reel|post|story|linkedin", "titulo": "...", "alcance": 992, "views": 1289, "curtidas": 39,
#             "comentarios": 2, "salvos": 4, "compart": 8, "extra": "retenção média 10,0 s", "img": "url opcional"}],
#  "referencia": {"post": 85, "reel": 640, "story": 30, "linkedin": 0},   (alcance médio dos últimos 14 dias por tipo; 0 = sem base)
#  "funcionou": ["..."], "nao_funcionou": ["..."], "licoes": ["..."], "proximas": ["..."],
#  "decisao": "a decisão ou conversa que o Márcio deveria ter hoje", "ressalvas": "limites dos dados (opcional)"}
TIPO_AN = {'reel': 'REEL', 'post': 'POST', 'story': 'STORY', 'linkedin': 'LINKEDIN'}
TOM = {'bom': '#0A8F5A', 'ruim': '#C0392B', 'neutro': '#4b5b70'}


def num(v):
    if v is None or v == '':
        return '–'
    try:
        v = float(v)
    except Exception:
        return esc(str(v))
    if v >= 1000:
        return f'{v / 1000:.1f}'.replace('.', ',') + ' mil'
    return str(int(v)) if v == int(v) else f'{v:.1f}'.replace('.', ',')


def manchete_html(an):
    if not an or not an.get('manchete'):
        return ''
    return (f'<div style="background:#0D1B3E;color:#fff;padding:14px 16px;margin:0 0 16px">'
            f'<div style="font-size:11px;letter-spacing:.16em;font-weight:700;color:#00D4D6">LEITURA DE ONTEM</div>'
            f'<div style="font-size:16px;line-height:1.4;margin-top:6px">{esc(an["manchete"])}</div></div>')


def renderiza_analise(an, out):
    pecas = an.get('pecas', [])
    ref = an.get('referencia', {})
    mx = max([p.get('alcance') or 0 for p in pecas] + [v or 0 for v in ref.values()] + [1])
    kpis = ''.join(
        f'<div style="flex:1;min-width:0;border-top:6px solid {TOM.get(k.get("tom"), TOM["neutro"])};background:#F4F7FC;padding:22px 24px">'
        f'<div style="font-size:16px;font-weight:700;letter-spacing:.12em;color:#4b5b70;text-transform:uppercase">{esc(k["rotulo"])}</div>'
        f'<div style="font-size:46px;font-weight:900;color:#0D1B3E;margin-top:8px;line-height:1">{esc(k["valor"])}</div>'
        f'<div style="font-size:18px;color:{TOM.get(k.get("tom"), TOM["neutro"])};margin-top:10px;font-weight:700">{esc(k.get("delta", ""))}</div></div>'
        for k in an.get('kpis', [])[:4])
    linhas = ''
    for i, p in enumerate(pecas):
        img = f'<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:13px;font-weight:700;letter-spacing:.12em;color:#8a94a6">{TIPO_AN.get(p.get("tipo"), "")}</div>'
        if p.get('img'):
            f = out / 'img' / f'an{i}.jpg'
            if baixa(p['img'], str(f)):
                img = f'<img src="img/an{i}.jpg" style="width:100%;height:100%;object-fit:cover;display:block">'
        w = round(560 * (p.get('alcance') or 0) / mx)
        r = ref.get(p.get('tipo'), 0) or 0
        marca = (f'<div title="média" style="position:absolute;left:{round(560 * r / mx)}px;top:-6px;bottom:-6px;width:3px;background:#C98A00"></div>'
                 f'<div style="position:absolute;left:{round(560 * r / mx) + 6}px;top:-26px;font-size:14px;color:#8a5a00;white-space:nowrap">média {TIPO_AN.get(p.get("tipo"), "").lower()}: {num(r)}</div>') if r else ''
        cor = '#0082C8' if (not r or (p.get('alcance') or 0) >= r) else '#8fb3cc'
        det = ' · '.join(x for x in [
            f'{num(p.get("views"))} views' if p.get('views') is not None else '',
            f'{num(p.get("curtidas"))} curtidas' if p.get('curtidas') is not None else '',
            f'{num(p.get("comentarios"))} coment.' if p.get('comentarios') is not None else '',
            f'{num(p.get("salvos"))} salvos' if p.get('salvos') is not None else '',
            f'{num(p.get("compart"))} compart.' if p.get('compart') is not None else '',
            esc(p.get('extra', ''))] if x)
        linhas += f"""<div style="display:flex;gap:22px;align-items:center;padding:18px 0;border-bottom:1px solid #e3eaf3">
 <div style="width:84px;height:105px;flex:none;background:#F4F7FC;border:1px solid #d5deea;overflow:hidden">{img}</div>
 <div style="flex:1;min-width:0">
  <div style="font-size:15px;font-weight:700;letter-spacing:.14em;color:#0082C8">{esc(p.get("hora", ""))} · {TIPO_AN.get(p.get("tipo"), "")}</div>
  <div style="font-size:24px;font-weight:700;color:#0D1B3E;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{esc(p.get("titulo", ""))}</div>
  <div style="display:flex;align-items:center;gap:16px;margin-top:22px"><div style="position:relative;width:560px;height:20px;background:#eef3f9"><div style="width:{w}px;height:20px;background:{cor}"></div>{marca}</div>
   <div style="font-size:24px;font-weight:900;color:#0D1B3E">{num(p.get("alcance"))}</div><div style="font-size:15px;color:#6b7a90">alcance</div></div>
  <div style="font-size:16px;color:#4b5b70;margin-top:8px">{det}</div>
 </div></div>"""
    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Exo+2:wght@300;400;700;900&display=swap">
<style>body{{margin:0;background:#fff;font-family:'Exo 2',system-ui,sans-serif}}</style></head><body>
<div id="c" style="width:1200px;background:#fff">
 <div style="background:#0D1B3E;padding:40px 60px 36px">
  <div style="font-size:17px;font-weight:700;letter-spacing:.22em;color:#00D4D6">META.X · ONTEM EM NÚMEROS</div>
  <div style="font-size:52px;font-weight:900;color:#fff;line-height:1.05;margin-top:10px">{esc((an.get("dia_semana", "") + ", ").capitalize() if an.get("dia_semana") else "")}{esc(an.get("data_ref", ""))}</div>
 </div>
 <div style="height:8px;background:linear-gradient(90deg,#0082C8,#00D4D6)"></div>
 <div style="padding:40px 60px 46px">
  <div style="display:flex;gap:18px">{kpis}</div>
  <div style="margin-top:40px;font-size:15px;font-weight:700;letter-spacing:.16em;color:#0082C8">CADA PEÇA · ALCANCE (CONTAS ÚNICAS) CONTRA A MÉDIA DOS ÚLTIMOS 14 DIAS</div>
  <div style="margin-top:8px">{linhas if linhas else '<div style="font-size:22px;color:#4b5b70;padding:20px 0">Nenhuma peça publicada ontem.</div>'}</div>
  <div style="margin-top:26px;font-size:15px;color:#6b7a90;line-height:1.5">Fonte: Instagram e LinkedIn via Windsor, lidos às 8h. Números de peças com menos de 24 h ainda vão crescer.</div>
 </div>
</div><script>document.fonts.ready.then(()=>{{window.pronto=true}})</script></body></html>"""
    (out / 'analise.html').write_text(pagina, encoding='utf-8')
    with sync_playwright() as pw:
        br = pw.chromium.launch(args=['--allow-file-access-from-files'])
        pg = br.new_page(viewport={'width': 1200, 'height': 900}, device_scale_factor=1)
        pg.goto((out / 'analise.html').resolve().as_uri(), wait_until='networkidle')
        try:
            pg.wait_for_function('window.pronto===true', timeout=15000)
        except Exception:
            pass
        pg.locator('#c').screenshot(path=str(out / 'analise.png'))
        br.close()
    from PIL import Image
    Image.open(out / 'analise.png').convert('RGB').save(out / 'analise.jpg', 'JPEG', quality=86, optimize=True, progressive=True)


def html_analise(an):
    def bloco(tit, itens, cor):
        if not itens:
            return '', ''
        lis = ''.join(f'<li style="margin:0 0 8px">{esc(x)}</li>' for x in itens)
        return (f'<p style="margin:18px 0 6px;font-size:12px;letter-spacing:.14em;font-weight:700;color:{cor}">{tit}</p>'
                f'<ul style="margin:0;padding-left:20px;color:#1d2b45;font-size:14px;line-height:1.5">{lis}</ul>',
                f'\n\n{tit}\n' + '\n'.join(f'- {x}' for x in itens))
    partes = [bloco('O QUE FUNCIONOU', an.get('funcionou'), '#0A8F5A'), bloco('O QUE NÃO FUNCIONOU', an.get('nao_funcionou'), '#C0392B'),
              bloco('LIÇÕES', an.get('licoes'), '#0082C8'), bloco('PARA AS PRÓXIMAS POSTAGENS', an.get('proximas'), '#0D1B3E')]
    dec = an.get('decisao', '')
    dec_h = (f'<div style="margin-top:18px;border-left:5px solid #C98A00;background:#fff8e6;padding:12px 14px"><div style="font-size:11px;letter-spacing:.14em;font-weight:700;color:#8a5a00">DECISÃO PARA HOJE</div>'
             f'<div style="font-size:15px;color:#3d2a00;margin-top:4px;line-height:1.45">{esc(dec)}</div></div>') if dec else ''
    res = an.get('ressalvas', '')
    res_h = f'<p style="margin:14px 0 0;color:#6b7a90;font-size:12px;line-height:1.5">Sobre os dados: {esc(res)}</p>' if res else ''
    h = (f'<div style="margin-top:30px;border-top:3px solid #0082C8;padding-top:16px">'
         f'<p style="margin:0 0 10px;font-size:13px;letter-spacing:.16em;font-weight:700;color:#0082C8">ANÁLISE DE ONTEM · {esc(an.get("data_ref", ""))}</p>'
         f'<img src="cid:att1" width="600" alt="Ontem em números" style="width:100%;max-width:600px;height:auto;display:block;border:0">'
         + ''.join(x[0] for x in partes) + dec_h + res_h + '</div>')
    t = f'\n\n----\nANÁLISE DE ONTEM ({an.get("data_ref", "")})\n{an.get("manchete", "")}' + ''.join(x[1] for x in partes) + (f'\n\nDECISÃO PARA HOJE\n{dec}' if dec else '')
    return h, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('calendario'); ap.add_argument('dia', type=int); ap.add_argument('saida', nargs='?', default='saida-email')
    ap.add_argument('--mes', type=int, default=11); ap.add_argument('--ano', type=int, default=2026)
    ap.add_argument('--analise', default=None, help='analise.json com as métricas e a leitura do dia anterior')
    a = ap.parse_args()
    M = carrega(a.calendario)
    FEED, STORIES = M['FEED'], M['STORIES']
    ROTULO, NOTAS = M.get('ROTULO', {}), M.get('NOTAS', {})
    CAPA.update(M.get('CAPA', {}))  # capas registradas no calendario.py do Projeto valem mais que as daqui
    STORY_VIDEO.update(M.get('STORY_VIDEO', {}))
    out = pathlib.Path(a.saida); (out / 'img').mkdir(parents=True, exist_ok=True)
    data = datetime.date(a.ano, a.mes, a.dia)
    dd = a.dia

    itens = []  # (hora, tipo, dados)
    for it in FEED:
        d, hr, kind, tone, tit, art, chips, nota = it
        if d != dd:
            continue
        img = None
        f = CAPA.get((d, hr))
        if f and baixa(BASE + f, str(out / 'img' / f)):
            img = 'img/' + f
        st = chips[0][1] if chips else 'ag'
        redes = ' + '.join(REDE.get(c[0], c[0]) for c in chips)
        itens.append({'hora': hr, 'kind': kind, 'tone': tone, 'titulo': tit, 'img': img, 'status': st, 'redes': redes, 'nota': nota,
                      'url_capa': (BASE + f) if img else ''})
    for s in STORIES.get(dd, []):
        art, hr, rot, st = s
        vid = STORY_VIDEO.get(art) or (art + '.mp4' if art.startswith('st-') or art.startswith('gs-') else None)
        img = None
        if vid:
            nome = re.sub(r'[^a-z0-9-]', '', vid.replace('.mp4', '')) + f'-{hr.replace(":", "")}.jpg'
            if quadro_story(vid, str(out / 'img' / nome)):
                img = 'img/' + nome
        itens.append({'hora': hr, 'kind': 'story', 'tone': '', 'titulo': rot, 'img': img, 'status': st, 'redes': 'Instagram', 'nota': ''})
    itens.sort(key=lambda x: x['hora'])

    nfeed = [i for i in itens if i['kind'] != 'story']
    cont = {k: sum(1 for i in itens if i['kind'] == k and i['status'] != 'off') for k in ('post', 'reel', 'story')}
    PLURAL = {'post': 'posts', 'reel': 'reels', 'story': 'stories'}
    resumo = ', '.join(f'{n} {PLURAL[k] if n > 1 else k}' for k, n in cont.items() if n)
    titulo_dia = f'{SEMANA[data.weekday()].capitalize()}, {dd} de {MESES[a.mes]}'

    # próximos dias (amanhã) e atenção (pronto/criar nos próximos 7 dias)
    prox = sorted({it[0] for it in FEED if it[0] > dd})
    amanha = prox[0] if prox else None
    am_itens = [it for it in FEED if it[0] == amanha] if amanha else []
    atencao = [it for it in FEED if dd <= it[0] <= dd + 7 and any(c[1] in ('pronto', 'criar', 'ok') for c in it[6])]

    # ------------------------------------------------------------ imagem do e-mail (HTML -> JPG)
    def thumb(i, w=132):
        if i['kind'] == 'story':
            w = round(w * 0.74)
        h = round(w * (16 / 9)) if i['kind'] == 'story' else round(w * 1.25)
        bg = '#071228' if i.get('tone') == 'E' else '#F4F7FC'
        if i['img']:
            inner = f'<img src="{i["img"]}" style="width:100%;height:100%;object-fit:cover;display:block">'
        else:
            fg = '#fff' if i.get('tone') == 'E' else '#0D1B3E'
            inner = f'<div style="display:flex;align-items:center;justify-content:center;height:100%;padding:10px;box-sizing:border-box;text-align:center;font-weight:700;font-size:15px;color:{fg};border:2px dashed #8a94a6">{esc(STATUS.get(i["status"], ""))}</div>'
        play = ''
        if i['kind'] == 'reel':
            play = '<div style="position:absolute;right:6px;top:6px;width:30px;height:30px;background:rgba(7,18,40,.82);display:flex;align-items:center;justify-content:center"><div style="width:0;height:0;border-left:11px solid #fff;border-top:7px solid transparent;border-bottom:7px solid transparent;margin-left:3px"></div></div>'
        return f'<div style="position:relative;width:{w}px;height:{h}px;flex:none;background:{bg};border:1px solid #d5deea;overflow:hidden">{inner}{play}</div>'

    CHIP = {'pub': 'background:#0D1B3E;color:#fff;border:2px solid #0D1B3E', 'ag': 'background:#fff;color:#0D1B3E;border:2px solid #0082C8',
            'pronto': 'background:#fff;color:#7a5200;border:2px dashed #c98a00', 'ok': 'background:#fff4d6;color:#5c3d00;border:2px dashed #8a5a00',
            'criar': 'background:#fff;color:#4b5b70;border:2px dashed #4b5b70', 'off': 'background:#fff;color:#8a94a6;border:2px solid #c8cfd9'}
    TIPO = {'post': 'POST NO FEED', 'reel': 'REEL', 'story': 'STORY'}

    linhas = ''
    for k, i in enumerate(itens):
        tom = ''
        if i['kind'] != 'story':
            cor = '#071228' if i['tone'] == 'E' else '#F4F7FC'
            tom = f'<span style="display:inline-flex;align-items:center;gap:6px;font-size:15px;color:#4b5b70"><span style="width:14px;height:14px;background:{cor};border:1px solid #8a94a6;display:inline-block"></span>{"capa escura" if i["tone"] == "E" else "capa clara"}</span>'
        nota = f'<div style="font-size:15px;color:#4b5b70;margin-top:6px">{esc(i["nota"])}</div>' if i['nota'] else ''
        fim = k == len(itens) - 1
        linhas += f'''<div style="display:flex;gap:26px;align-items:stretch">
 <div style="width:104px;flex:none;text-align:right;padding-top:4px"><div style="font-size:38px;font-weight:700;color:#0D1B3E;letter-spacing:-0.02em">{i["hora"]}</div></div>
 <div style="width:22px;flex:none;position:relative;display:flex;justify-content:center"><div style="position:absolute;top:18px;bottom:{"auto" if fim else "-26px"};{"height:0;" if fim else ""}width:3px;background:#cfe3f3"></div><div style="position:relative;margin-top:14px;width:18px;height:18px;border-radius:50%;background:{"#00D4D6" if i["kind"] == "story" else "#0082C8"};border:3px solid #fff;box-shadow:0 0 0 2px #0082C8"></div></div>
 <div style="width:132px;flex:none;display:flex;justify-content:center">{thumb(i)}</div>
 <div style="flex:1;padding-top:6px;min-width:0">
  <div style="font-size:15px;font-weight:700;letter-spacing:.16em;color:#0082C8">{TIPO[i["kind"]]}</div>
  <div style="font-size:29px;font-weight:700;color:#0D1B3E;line-height:1.15;margin-top:6px">{esc(i["titulo"])}</div>
  <div style="font-size:17px;color:#33415C;margin-top:8px">{esc(i["redes"])}</div>
  <div style="display:flex;gap:14px;align-items:center;margin-top:12px;flex-wrap:wrap"><span style="padding:4px 10px;font-size:15px;font-weight:700;{CHIP.get(i["status"], CHIP["ag"])}">{STATUS.get(i["status"], "")}</span>{tom}</div>
  {nota}
 </div></div>'''
        if not fim:
            linhas += '<div style="height:26px"></div>'
    if not itens:
        linhas = '<div style="font-size:26px;color:#33415C;padding:20px 0">Nenhuma peça registrada para hoje no calendário do projeto.</div>'

    am_html = ''
    if am_itens:
        dam = datetime.date(a.ano, a.mes, amanha)
        cards = ''
        for it in am_itens:
            f = CAPA.get((it[0], it[1]))
            img = ('img/' + f) if f and baixa(BASE + f, str(out / 'img' / f)) else None
            ii = {'kind': it[2], 'tone': it[3], 'img': img, 'status': it[6][0][1] if it[6] else 'ag'}
            cards += f'<div style="display:flex;gap:14px;align-items:flex-start;width:330px">{thumb(ii, 84)}<div><div style="font-size:22px;font-weight:700;color:#0D1B3E">{it[1]}</div><div style="font-size:17px;color:#33415C;line-height:1.25;margin-top:4px">{esc(it[4])}</div><div style="font-size:14px;color:#0082C8;font-weight:700;margin-top:6px">{STATUS.get(ii["status"], "").upper()}</div></div></div>'
        am_html = f'''<div style="margin-top:44px;padding-top:30px;border-top:2px solid #e3eaf3">
 <div style="font-size:15px;font-weight:700;letter-spacing:.16em;color:#0082C8">{"AMANHÃ" if amanha == dd + 1 else "PRÓXIMO DIA COM POSTAGEM"} · {SEMANA[dam.weekday()].upper()}, {amanha:02d}/{a.mes:02d}</div>
 <div style="display:flex;gap:26px;flex-wrap:wrap;margin-top:18px">{cards}</div></div>'''

    at_html = ''
    if atencao:
        li = ''.join(f'<div style="font-size:19px;color:#5c3d00;margin-top:8px">• {it[0]:02d}/{a.mes:02d} {it[1]} · {esc(it[4])}: <b>{STATUS[[c[1] for c in it[6] if c[1] in ("pronto", "criar", "ok")][0]].lower()}</b></div>' for it in atencao)
        at_html = f'<div style="margin-top:36px;background:#fff8e6;border-left:6px solid #c98a00;padding:22px 26px"><div style="font-size:15px;font-weight:700;letter-spacing:.16em;color:#8a5a00">ATENÇÃO NOS PRÓXIMOS 7 DIAS</div>{li}</div>'

    rot = ROTULO.get(dd, '')
    nota_dia = NOTAS.get(dd, '')
    sub = ' · '.join(x for x in (rot, nota_dia) if x)
    pagina = f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Exo+2:wght@300;400;700;900&display=swap">
<style>body{{margin:0;background:#fff;font-family:'Exo 2',system-ui,sans-serif}}</style></head><body>
<div id="c" style="width:1200px;background:#fff">
 <div style="background:#0D1B3E;padding:44px 60px 40px;position:relative;overflow:hidden">
  <div style="position:absolute;right:-80px;top:-80px;width:320px;height:320px;border:40px solid rgba(0,130,200,.25);border-radius:50%"></div>
  <div style="font-size:17px;font-weight:700;letter-spacing:.22em;color:#00D4D6">META.X · PROGRAMAÇÃO DO DIA</div>
  <div style="font-size:62px;font-weight:900;color:#fff;line-height:1.05;margin-top:12px;letter-spacing:-0.01em">{titulo_dia}</div>
  <div style="font-size:24px;color:#b9c7dd;margin-top:14px">{esc(resumo) if resumo else "sem peças"}{(" · " + esc(sub)) if sub else ""}</div>
 </div>
 <div style="height:8px;background:linear-gradient(90deg,#0082C8,#00D4D6)"></div>
 <div style="padding:44px 60px 50px">{linhas}{am_html}{at_html}
  <div style="margin-top:40px;font-size:16px;color:#6b7a90;line-height:1.5">Horários de Brasília. Publicação automática no @metax.ind e na página Meta.X no LinkedIn. Para segurar uma peça, avise o Márcio antes do horário.</div>
 </div>
</div><script>document.fonts.ready.then(()=>{{window.pronto=true}})</script></body></html>'''
    (out / 'agenda.html').write_text(pagina, encoding='utf-8')
    with sync_playwright() as p:
        br = p.chromium.launch(args=['--allow-file-access-from-files'])
        pg = br.new_page(viewport={'width': 1200, 'height': 900}, device_scale_factor=1)
        pg.goto((out / 'agenda.html').resolve().as_uri(), wait_until='networkidle')
        try:
            pg.wait_for_function('window.pronto===true', timeout=15000)
        except Exception:
            pass
        pg.locator('#c').screenshot(path=str(out / 'agenda.png'))
        br.close()
    from PIL import Image
    Image.open(out / 'agenda.png').convert('RGB').save(out / 'agenda.jpg', 'JPEG', quality=86, optimize=True, progressive=True)

    an = json.load(open(a.analise, encoding='utf-8')) if a.analise else None
    an_html, an_txt = '', ''
    if an:
        # capa de cada peça de ontem: a do calendário (mesmo dia, mesmo tipo, horário mais próximo, até 90 min)
        try:
            d_ref = int(str(an.get('data_ref', '')).split('/')[0])
        except Exception:
            d_ref = None
        def minutos(h):
            try:
                hh, mm = str(h).split(':')[:2]; return int(hh) * 60 + int(mm)
            except Exception:
                return None
        for pc in an.get('pecas', []):
            if pc.get('img') or d_ref is None or minutos(pc.get('hora')) is None:
                continue
            tipo = 'post' if pc.get('tipo') in ('post', 'linkedin') else pc.get('tipo')
            mesmo = [it for it in FEED if it[0] == d_ref and it[4].strip().lower() == str(pc.get('titulo', '')).strip().lower()]
            if mesmo and CAPA.get((d_ref, mesmo[0][1])):
                pc['img'] = BASE + CAPA[(d_ref, mesmo[0][1])]
                continue
            cands = [it for it in FEED if it[0] == d_ref and it[2] == tipo and minutos(it[1]) is not None]
            cands.sort(key=lambda it: abs(minutos(it[1]) - minutos(pc['hora'])))
            if cands and abs(minutos(cands[0][1]) - minutos(pc['hora'])) <= 90:
                f = CAPA.get((d_ref, cands[0][1]))
                if f:
                    pc['img'] = BASE + f
        renderiza_analise(an, out)
        an_html, an_txt = html_analise(an)

    # ------------------------------------------------------------ corpo do e-mail
    assunto = f'Meta.X · Programação de {SEMANA[data.weekday()]}, {dd:02d}/{a.mes:02d}' + (f': {resumo}' if resumo else '')
    txt_l = [f'{i["hora"]}  {TIPO[i["kind"]].capitalize()}: {i["titulo"]} ({i["redes"]}) · {STATUS.get(i["status"], "")}' for i in itens]
    corpo_txt = f'{titulo_dia}\n\n' + ('\n'.join(txt_l) if txt_l else 'Nenhuma peça registrada para hoje.') + '\n\nHorários de Brasília.' + an_txt
    tab = ''.join(f'<tr><td style="padding:6px 12px 6px 0;font-weight:700;color:#0D1B3E;white-space:nowrap;vertical-align:top">{i["hora"]}</td>'
                  f'<td style="padding:6px 0;color:#33415C">{TIPO[i["kind"]].capitalize()}: <b>{esc(i["titulo"])}</b> · {esc(i["redes"])} · {STATUS.get(i["status"], "")}</td></tr>' for i in itens)
    corpo_html = f'''<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px">
<p style="margin:0 0 14px;color:#0D1B3E;font-size:15px">Bom dia! Esta é a programação de postagens da Meta.X para hoje{", com a leitura do que aconteceu ontem" if an else ""}.</p>
{manchete_html(an)}
<img src="cid:att0" width="600" alt="Programação do dia" style="width:100%;max-width:600px;height:auto;display:block;border:0">
<table style="margin-top:18px;font-size:14px;border-collapse:collapse">{tab}</table>
{an_html}
<p style="margin:18px 0 0;color:#6b7a90;font-size:12px">Horários de Brasília. E-mail automático enviado todo dia às 8h.</p></div>'''
    (out / 'assunto.txt').write_text(assunto, encoding='utf-8')
    (out / 'corpo.txt').write_text(corpo_txt, encoding='utf-8')
    (out / 'corpo.html').write_text(corpo_html, encoding='utf-8')
    lembretes = [{'data': data.isoformat(), 'hora': i['hora'], 'tipo': i['kind'], 'titulo': i['titulo'], 'redes': i['redes'],
                  'status': i['status'], 'capa': i.get('url_capa', '')} for i in nfeed]
    (out / 'lembretes.json').write_text(json.dumps(lembretes, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'assunto': assunto, 'itens': len(itens), 'jpg_kb': os.path.getsize(out / 'agenda.jpg') // 1024,
                      'analise_jpg': (out / 'analise.jpg').exists(),
                      'sem_imagem': [i['titulo'] for i in itens if not i['img']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
