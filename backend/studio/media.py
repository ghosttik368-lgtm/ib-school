"""Local file responses with byte ranges for video seeking and PDF viewers."""
import mimetypes
import re
from pathlib import Path
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header


def file_response(request, path, name):
    filename=Path(path)
    total=filename.stat().st_size
    inline=Path(name).suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif','.pdf','.mp4','.webm'}
    content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream'
    range_header=request.headers.get('Range','')
    if range_header and request.method=='GET':
        match=re.fullmatch(r'bytes=(\d*)-(\d*)',range_header)
        start,end=0,total-1
        try:
            if not match or not any(match.groups()):raise ValueError
            left,right=match.groups()
            if left:
                start=int(left);end=min(int(right),total-1) if right else total-1
            else:
                length=int(right)
                if length<=0:raise ValueError
                start=max(0,total-length)
            if not 0<=start<=end<total:raise ValueError
        except (ValueError,OverflowError):
            response=HttpResponse(status=416)
            response['Content-Range']=f'bytes */{total}'
            return response
        def chunks():
            with filename.open('rb') as stream:
                stream.seek(start);remaining=end-start+1
                while remaining:
                    data=stream.read(min(65536,remaining))
                    if not data:break
                    remaining-=len(data);yield data
        response=StreamingHttpResponse(chunks(),status=206,content_type=content_type)
        response['Content-Length']=str(end-start+1)
        response['Content-Range']=f'bytes {start}-{end}/{total}'
        response['Content-Disposition']=content_disposition_header(not inline,name)
    elif request.method=='HEAD':
        response=HttpResponse(content_type=content_type)
        response['Content-Length']=str(total)
        response['Content-Disposition']=content_disposition_header(not inline,name)
    else:
        response=FileResponse(filename.open('rb'),as_attachment=not inline,filename=name,content_type=content_type)
    response['Accept-Ranges']='bytes'
    response['X-Frame-Options']='SAMEORIGIN'
    response['Content-Security-Policy']="sandbox; frame-ancestors 'self'"
    response['X-Content-Type-Options']='nosniff'
    return response
