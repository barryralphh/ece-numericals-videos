import sys, os, math, subprocess, asyncio
from functools import lru_cache
import yaml
from PIL import Image, ImageDraw, ImageFont
import edge_tts

W, H, FPS = 1280, 720, 24
VOICE = os.environ.get('VOICE', 'hi-IN-SwaraNeural')
RATE = os.environ.get('RATE', '-4%')
FD = '/usr/share/fonts/truetype/dejavu/'

@lru_cache(None)
def font(s, b=False):
    return ImageFont.truetype(FD + ('DejaVuSans-Bold.ttf' if b else 'DejaVuSans.ttf'), s)

C = {'white': (240, 244, 255), 'yellow': (255, 214, 10), 'green': (46, 230, 140),
     'red': (255, 100, 110), 'cyan': (80, 215, 255), 'orange': (255, 170, 70), 'dim': (150, 160, 200)}
KIND = {'F': ('FORMULA', C['cyan']), 'A': ('ANSWER', C['green']), 'T': ('TRAP', C['red']),
        'S': ('SHORTCUT', C['orange']), 'Q': ('TRY IT', C['yellow'])}
BOXBG = (20, 24, 56)

def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def eo(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3

def make_bg():
    im = Image.new('RGB', (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=lerp((12, 18, 44), (34, 16, 74), y / H))
    return im

BG = make_bg()

def parse(l):
    if len(l) > 2 and l[1] == '|' and l[0] in KIND:
        return l[0], l[2:]
    return 'N', l

def fit(text, maxw, size, bold=False):
    while size > 20:
        f = font(size, bold)
        if f.getlength(text) <= maxw:
            return f
        size -= 2
    return font(20, bold)

def draw_line(d, kind, text, x, y, maxw, p, t):
    e = eo(p)
    if e <= 0:
        return
    xx = x - int((1 - e) * 70)
    if kind == 'N':
        col = lerp(BOXBG, C['white'], e)
        d.text((xx + 10, y + 12), text, font=fit(text, maxw - 20, 40), fill=col)
        return
    label, base = KIND[kind]
    col = lerp(BOXBG, base, e)
    bw = 3 + (int(2 * (1 + math.sin(t * 6))) if kind == 'A' else 0)
    d.rounded_rectangle([xx, y, xx + maxw, y + 72], radius=14, outline=col, width=bw,
                        fill=lerp(BOXBG, base, 0.12 * e))
    d.text((xx + 16, y + 3), label, font=font(15, True), fill=col)
    tc = lerp(BOXBG, base if kind == 'A' else C['white'], e)
    d.text((xx + 20, y + 20), text, font=fit(text, maxw - 40, 40, kind in 'AF'), fill=tc)

def viz(d, kind, sc, t):
    x0, y0, x1, y1 = 830, 150, 1240, 540
    d.rounded_rectangle([x0, y0, x1, y1], radius=18, outline=C['dim'], width=2)
    w = x1 - x0 - 40
    cy = (y0 + y1) // 2
    n = int(min(1.0, t / 2.0) * w)
    if kind == 'sine':
        f = sc.get('freq', 2)
        d.line([(x0 + 20, cy), (x1 - 20, cy)], fill=C['dim'], width=1)
        pts = [(x0 + 20 + i, cy - int(110 * math.sin(2 * math.pi * f * i / w + t * 2))) for i in range(n)]
        if len(pts) > 1:
            d.line(pts, fill=C['cyan'], width=4)
    elif kind == 'am':
        env = lambda i: 0.55 + 0.4 * math.sin(2 * math.pi * i / w + t)
        up = [(x0 + 20 + i, cy - int(130 * env(i))) for i in range(n)]
        dn = [(x0 + 20 + i, cy + int(130 * env(i))) for i in range(n)]
        car = [(x0 + 20 + i, cy - int(130 * env(i) * math.sin(2 * math.pi * 14 * i / w + t * 8))) for i in range(n)]
        for pts, c, wd in ((car, C['cyan'], 2), (up, C['yellow'], 3), (dn, C['yellow'], 3)):
            if len(pts) > 1:
                d.line(pts, fill=c, width=wd)
    elif kind == 'spectrum':
        bars = sc.get('bars', [])
        m = max(1, len(bars))
        base = y1 - 50
        d.line([(x0 + 15, base), (x1 - 15, base)], fill=C['dim'], width=2)
        for k, (lab, hh) in enumerate(bars):
            bx = x0 + 20 + (k + 0.5) * w / m
            ph = hh * (base - y0 - 40) * eo((t - 0.3 - 0.25 * k) / 0.8)
            d.rectangle([bx - 14, base - ph, bx + 14, base], fill=C['green'])
            d.text((bx - font(18).getlength(lab) / 2, base + 8), lab, font=font(18), fill=C['white'])

def frame(spec, sc, i, ns, lines, t, dur, gt, total):
    im = BG.copy()
    d = ImageDraw.Draw(im)
    for k in range(9):
        r = 40 + k * 18
        cx = (k * 163 + gt * (12 + k * 3)) % (W + 200) - 100
        cy = 120 + ((k * 97) % 520) + int(18 * math.sin(gt * 0.8 + k))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(40, 34, 92), width=3)
    d.rectangle([0, 0, W, 90], fill=(10, 12, 30))
    d.text((40, 24), spec['title'], font=font(34, True), fill=C['yellow'])
    badge = sc.get('step', '%d/%d' % (i + 1, ns))
    bf = font(24, True)
    tw = bf.getlength(badge)
    d.rounded_rectangle([W - tw - 80, 22, W - 30, 68], radius=22, fill=C['cyan'])
    d.text((W - tw - 55, 28), badge, font=bf, fill=(10, 12, 30))
    d.text((40, 104), sc.get('head', ''), font=font(30, True), fill=C['orange'])
    vk = sc.get('viz')
    maxw = 770 if vk else 1200
    span = max(1.0, dur - 1.6 - sc.get('pause', 0))
    for k, (kind, text) in enumerate(lines):
        st = 0.4 + k * span / max(1, len(lines))
        draw_line(d, kind, text, 40, 150 + k * 86, maxw, (t - st) / 0.5, t)
    if vk:
        viz(d, vk, sc, t)
    d.rectangle([0, H - 10, int(W * gt / total), H], fill=C['green'])
    return im

async def tts(text, path):
    err = None
    for a in range(5):
        try:
            await edge_tts.Communicate(text, VOICE, rate=RATE).save(path)
            if os.path.getsize(path) > 800:
                return
        except Exception as e:
            err = e
            print('tts retry', a, e, flush=True)
        await asyncio.sleep(2 + a * 2)
    raise RuntimeError('TTS failed: %s' % err)

def run(cmd):
    subprocess.run(cmd, check=True)

def adur(path):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path]))

def main(path):
    spec = yaml.safe_load(open(path, encoding='utf-8'))
    slug = os.path.splitext(os.path.basename(path))[0]
    os.makedirs('out', exist_ok=True)
    tmp = os.path.join('tmp', slug)
    os.makedirs(tmp, exist_ok=True)
    scenes = spec['scenes']
    durs = []
    for i, sc in enumerate(scenes):
        mp3 = '%s/s%d.mp3' % (tmp, i)
        asyncio.run(tts(sc['say'], mp3))
        durs.append(adur(mp3) + 0.7 + sc.get('pause', 0))
        print('scene', i, 'audio ok', round(durs[-1], 1), flush=True)
    with open(tmp + '/list.txt', 'w') as lst:
        for i, dd in enumerate(durs):
            run(['ffmpeg', '-y', '-loglevel', 'error', '-i', '%s/s%d.mp3' % (tmp, i), '-af', 'apad=whole_dur=%.3f' % dd,
                 '-ar', '44100', '-ac', '1', '%s/s%d.wav' % (tmp, i)])
            lst.write('file s%d.wav' % i + chr(10))
    run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', tmp + '/list.txt', '-c', 'copy', tmp + '/audio.wav'])
    out = 'out/%s.mp4' % slug
    p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H),
                          '-r', str(FPS), '-i', '-', '-i', tmp + '/audio.wav', '-c:v', 'libx264', '-preset', 'veryfast',
                          '-crf', '24', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-shortest', out], stdin=subprocess.PIPE)
    total = sum(durs)
    done = 0.0
    for i, (sc, dur) in enumerate(zip(scenes, durs)):
        lines = [parse(l) for l in sc.get('lines', [])]
        n = int(dur * FPS)
        for fr in range(n):
            t = fr / FPS
            p.stdin.write(frame(spec, sc, i, len(scenes), lines, t, dur, done + t, total).tobytes())
        done += n / FPS
    p.stdin.close()
    p.wait()
    print('DONE', out, round(total), 'sec', flush=True)

if __name__ == '__main__':
    main(sys.argv[1])
