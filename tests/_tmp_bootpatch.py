import subprocess, tests.test_boot as tb
_orig = subprocess.run
def run(cmd, **kw):
    if cmd[:2]==["node","--test"]:
        kw.pop("capture_output",None); kw.pop("text",None)
        with open("/tmp/claude-1000/-mnt-c-Users-jujuz-Documents-Portifolio/b3dbaa80-f7be-40f8-aeee-c4e8214821a0/scratchpad/boot_out.txt","w") as f:
            try: return _orig(cmd, stdout=f, stderr=subprocess.STDOUT, **kw)
            except subprocess.TimeoutExpired: raise
    return _orig(cmd, **kw)
tb.subprocess.run = run
