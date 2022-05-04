import re, os, stat

patterns = [ (re.compile(a), b) for a, b in [
    (r'^(/tftpboot/)', r'/tftpboot/'),
    (r'^/tftpboot/', r'/tftpboot/'),
    (r'^(^/)', r'/tftpboot/\1'),
    (r'^([^/])', r'/tftpboot/\1')
]]

# filename -> (stream, size)
def handle(self, filename):
    for pattern, replacement in patterns:
        if pattern.search(filename):
            new_filename = pattern.sub(replacement, filename)
            return open(new_filename, 'rb'), os.stat(new_filename)[stat.ST_SIZE]