"""Binary media archive on stdout/stdin; restore only into an empty volume."""
from pathlib import Path
import sys
import tarfile

root = Path('/app/backend/media')
if sys.argv[1:] == ['pack']:
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz') as archive:
        for child in sorted(root.iterdir()):
            archive.add(child, arcname=child.name, recursive=True)
elif sys.argv[1:] == ['unpack']:
    if any(root.iterdir()):
        sys.exit('Media volume must be empty before restore.')
    with tarfile.open(fileobj=sys.stdin.buffer, mode='r|gz') as archive:
        for member in archive:
            if not (member.isfile() or member.isdir()):
                sys.exit('Links/special files are not accepted in media archives.')
            dest = (root / member.name).resolve()
            if not dest.is_relative_to(root) or dest == root:
                sys.exit('Invalid archive path.')
            member.uid = member.gid = 10001
            member.uname = member.gname = 'app'
            archive.extract(member, path=root, filter='data')
else:
    sys.exit('Usage: media_archive.py pack|unpack')
