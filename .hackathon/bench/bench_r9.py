"""R9 channel bench: 3 sizes per function (scratch, not project source)."""
import time
from wards.channels import ChannelEvidence, clean_channel_text, build_output_rename_map, clean_dict_keys

def t(fn):
    s = time.perf_counter(); fn(); return time.perf_counter() - s

ev = ChannelEvidence()
import itertools, string
WORDS = ["".join(w) for w in itertools.islice(itertools.product("bcdfgklmnprstv", "aeiou", "rstnl", "aeiou", "kmnpr"), 1000)]
for i in range(500):
    ev.add_name(f"{WORDS[2*i].title()} {WORDS[2*i+1].title()}", "PATIENT_NAME")
ev.add_mrn("UHID-901234")
unit = f"{WORDS[14].title()}_{WORDS[15].title()}_UHID-901234_Dr_Meera_Kulkarni_"
for n in (200, 2000, 20000):
    print("clean_channel_text", n, round(t(lambda: clean_channel_text(unit * n, ev, filename_safe=True)), 4))
for n in (200, 2000, 20000):
    paths = [f"notes/{WORDS[2*(i%500)].title()}_{WORDS[2*(i%500)+1].title()}.txt" for i in range(n)]
    print("rename_map(colliding)", n, round(t(lambda: build_output_rename_map(paths, ev)), 4))
for n in (1000, 4000, 16000):
    keys = [f"{WORDS[2*(i%500)].title()} {WORDS[2*(i%500)+1].title()}" for i in range(n)]
    print("clean_dict_keys(colliding, by_name)", n, round(t(lambda: clean_dict_keys(keys, ev, key_context="PATIENT_NAME")), 4))
