# -*- coding: utf-8 -*-

import re
import subprocess
import tempfile
import os
from urllib.parse import urljoin
from lxml import etree
from .httprequest import G_USER_AGENT
from .parser import Parser


class CurlResponse:
    def __init__(self, content, status_code, url):
        self.content = content
        self.status_code = status_code
        self.url = url
        self.ok = 200 <= status_code < 300

    @property
    def text(self):
        return self.content.decode('utf-8', errors='ignore')


class CurlSession:
    def __init__(self, cookies=None, proxies=None, verify=True):
        self.proxies = proxies
        self.verify = verify
        self.cookie_file = tempfile.NamedTemporaryFile(delete=False)
        self.cookie_file.close()
        self.cookie_path = self.cookie_file.name
        self.initial_cookies = cookies if cookies else {}

    def get(self, url):
        cmd = [
            'curl', '-L', '-s', '--compressed',
            '-w', '\n%{http_code}\n%{url_effective}',
            '-o', '-',
            '-A', G_USER_AGENT,
            '-b', self.cookie_path,
            '-c', self.cookie_path,
        ]

        if self.initial_cookies:
            cookie_str = '; '.join([f'{k}={v}' for k, v in self.initial_cookies.items()])
            cmd.extend(['-b', cookie_str])
            self.initial_cookies = {}

        if not self.verify:
            cmd.append('-k')

        if self.proxies:
            proxy = self.proxies.get('https') or self.proxies.get('http')
            if proxy:
                cmd.extend(['-x', proxy])

        cmd.append(url)

        result = subprocess.run(cmd, capture_output=True)
        output = result.stdout

        lines = output.split(b'\n')
        if len(lines) >= 3:
            effective_url = lines[-1].decode('utf-8', errors='ignore')
            status_code_str = lines[-2].decode('utf-8', errors='ignore')
            try:
                status_code = int(status_code_str)
            except ValueError:
                status_code = 0
            content = b'\n'.join(lines[:-2])
            if content.endswith(b'\n'):
                content = content[:-1]
        else:
            content = output
            status_code = 0
            effective_url = url

        return CurlResponse(content, status_code, effective_url)

    def __del__(self):
        if hasattr(self, 'cookie_path') and os.path.exists(self.cookie_path):
            try:
                os.remove(self.cookie_path)
            except:
                pass


class Javdb(Parser):
    source = 'javdb'

    # expr_number = '//a[contains(text(),"番號")]/../span/text()'
    expr_number = '//div[contains(@class, "panel-block")]/a[@data-clipboard-text]/@data-clipboard-text'
    # expr_number2 = '//strong[contains(text(),"番號")]/../span/a/text()'
    expr_title = "/html/head/title/text()"
    expr_title_no = '//*[contains(@class,"movie-list")]/div/a/div[contains(@class, "video-title")]/text()'
    expr_runtime = '//strong[contains(text(),"時長")]/../span/text()'
    expr_runtime2 = '//strong[contains(text(),"時長")]/../span/a/text()'
    expr_uncensored = '//strong[contains(text(),"類別")]/../span/a[contains(@href,"/tags/uncensored?") or contains(@href,"/tags/western?")]'
    expr_actor = '//span[@class="value"]/a[@class="actor-female" and contains(@href,"/actors/")]/text()'
    expr_actor2 = '//span[@class="value"]/a[contains(@href,"/actors/")]/@class'
    expr_release = '//strong[contains(text(),"日期")]/../span/text()'
    expr_release_no = '//*[contains(@class,"movie-list")]/div/a/div[contains(@class, "meta")]/text()'
    expr_studio = '//strong[contains(text(),"片商")]/../span/a/text()'
    expr_studio2 = '//strong[contains(text(),"賣家:")]/../span/a/text()'
    expr_director = '//strong[contains(text(),"導演")]/../span/text()'
    expr_director2 = '//strong[contains(text(),"導演")]/../span/a/text()'
    expr_cover = "//div[contains(@class, 'column-video-cover')]/a/img/@src"
    expr_cover2 = "//div[contains(@class, 'column-video-cover')]/img/@src"
    expr_cover_no = '//*[contains(@class,"movie-list")]/div/a/div[contains(@class, "cover")]/img/@src'
    expr_trailer = '//span[contains(text(),"預告片")]/../../video/source/@src'
    expr_extrafanart = "//article[@class='message video-panel']/div[@class='message-body']/div[@class='tile-images preview-images']/a[contains(@href,'/samples/')]/@href"
    expr_tags = '//strong[contains(text(),"類別")]/../span/a/text()'
    expr_tags2 = '//strong[contains(text(),"類別")]/../span/text()'
    expr_series = '//strong[contains(text(),"系列")]/../span/text()'
    expr_series2 = '//strong[contains(text(),"系列")]/../span/a/text()'
    expr_label = '//strong[contains(text(),"系列")]/../span/text()'
    expr_label2 = '//strong[contains(text(),"系列")]/../span/a/text()'
    expr_userrating = '//span[@class="score-stars"]/../text()'
    expr_uservotes = '//span[@class="score-stars"]/../text()'
    expr_actorphoto = '//strong[contains(text(),"演員:")]/../span/a[starts-with(@href,"/actors/")]'

    def extraInit(self):
        self.fixstudio = False
        self.noauth = False

    def updateCore(self, core):
        if core.proxies:
            self.proxies = core.proxies
        if core.verify:
            self.verify = core.verify
        if core.morestoryline:
            self.morestoryline = True
        if core.specifiedSource == self.source:
            self.specifiedUrl = core.specifiedUrl
        # special
        if core.dbcookies:
            self.cookies = core.dbcookies
        else:
            self.cookies =  {'over18':'1', 'theme':'auto', 'locale':'zh'}
        if core.dbsite:
            self.dbsite = core.dbsite
        else:
            self.dbsite = 'javdb'

    def search(self, number: str):
        self.number = number
        self.session = CurlSession(cookies=self.cookies, proxies=self.proxies, verify=self.verify)
        if self.specifiedUrl:
            self.detailurl = self.specifiedUrl
        else:
            self.detailurl = self.queryNumberUrl(number)
        self.deatilpage = self.session.get(self.detailurl).text
        if '此內容需要登入才能查看或操作' in self.deatilpage or '需要VIP權限才能訪問此內容' in self.deatilpage:
            self.noauth = True
            self.imagecut = 0
            result = self.dictformat(self.querytree)
        else:
            htmltree = etree.fromstring(self.deatilpage, etree.HTMLParser())
            result = self.dictformat(htmltree)
        return result

    def queryNumberUrl(self, number):
        javdb_url = 'https://' + self.dbsite + '.com/search?q=' + number + '&f=all'
        try:
            resp = self.session.get(javdb_url)
            self.querytree = etree.fromstring(resp.text, etree.HTMLParser()) 
            
            # 获取所有可能的URL和ID，添加长度检查和日志
            urls = self.getTreeAll(self.querytree, '//*[contains(@class,"movie-list")]/div/a/@href')
            if not urls:
                print(f'[!] {self.number}: No search results found in javdb')
                raise Exception(f'[!] {self.number}: No search results found in javdb')
            
            # 欧美影片的特殊处理
            if re.search(r'[a-zA-Z]+\.\d{2}\.\d{2}\.\d{2}', number):
                print(f'[+] {self.number}: Western video detected')
                correct_url = urls[0]
            else:
                ids = self.getTreeAll(self.querytree, '//*[contains(@class,"movie-list")]/div/a/div[contains(@class, "video-title")]/strong/text()')
                print(f'[+] {self.number}: Found {len(ids)} results: {ids}')
                
                try:
                    self.queryid = ids.index(number)
                    correct_url = urls[self.queryid]
                except ValueError:
                    # 检查第一个结果是否匹配
                    if not ids:
                        print(f'[!] {self.number}: No IDs found in search results')
                        raise ValueError("No IDs found in javdb search results")
                        
                    if ids[0].upper() != number.upper():
                        print(f'[!] {self.number}: Expected {number}, but found {ids[0]}')
                        raise ValueError(f"number not found in javdb (found: {ids[0]})")
                        
                    correct_url = urls[0]
                except IndexError as e:
                    print(f'[!] {self.number}: Index error - urls:{len(urls)}, ids:{len(ids)}')
                    raise IndexError(f"Index mismatch: urls({len(urls)}), ids({len(ids)})") from e
                
            return urljoin(resp.url, correct_url)
            
        except Exception as e:
            print(f'[!] {self.number}: Error in queryNumberUrl: {str(e)}')
            print(f'[!] Response status: {resp.status_code if "resp" in locals() else "N/A"}')
            print(f'[!] Response URL: {resp.url if "resp" in locals() else "N/A"}')
            raise

    def getNum(self, htmltree):
        if self.noauth:
            return self.number
        # 番号被分割开，需要合并后才是完整番号
        part1 = self.getTreeElement(htmltree, self.expr_number)
        # part2 = self.getTreeElement(htmltree, self.expr_number2)
        dp_number = part1
        # NOTE 检测匹配与更新 self.number
        if dp_number.upper() != self.number.upper():
            raise Exception(f'[!] {self.number}: find [{dp_number}] in javdb, not match')
        self.number = dp_number
        return self.number

    def getTitle(self, htmltree):
        if self.noauth:
            return self.getTreeElement(htmltree, self.expr_title_no, self.queryid)
        browser_title = super().getTitle(htmltree)
        title = browser_title[:browser_title.find(' | JavDB')].strip()
        return title.replace(self.number, '').strip()

    def getCover(self, htmltree):
        if self.noauth:
            return self.getTreeElement(htmltree, self.expr_cover_no, self.queryid)
        return super().getCover(htmltree)

    def getRelease(self, htmltree):
        if self.noauth:
            return self.getTreeElement(htmltree, self.expr_release_no, self.queryid).strip()
        return super().getRelease(htmltree)

    def getDirector(self, htmltree):
        return self.getTreeElementbyExprs(htmltree, self.expr_director, self.expr_director2)
    
    def getSeries(self, htmltree):
        # NOTE 不清楚javdb是否有一部影片多个series的情况，暂时保留
        results = self.getTreeAllbyExprs(htmltree, self.expr_series, self.expr_series2)
        result = ''.join(results)
        if not result and self.fixstudio:
            result = self.getStudio(htmltree)
        return result

    def getLabel(self, htmltree):
        results = self.getTreeAllbyExprs(htmltree, self.expr_label, self.expr_label2)
        result = ''.join(results)
        if not result and self.fixstudio:
            result = self.getStudio(htmltree)
        return result

    def getActors(self, htmltree):
        actors = self.getTreeAll(htmltree, self.expr_actor)
        # genders = self.getTreeAll(htmltree, self.expr_actor2)
        r = []
        idx = 0
        # NOTE only female, we dont care others
        actor_gendor = 'female'
        for act in actors:
            # if((actor_gendor == 'all')
            # or (actor_gendor == 'both' and genders[idx] in ['symbol female', 'symbol male'])
            # or (actor_gendor == 'female' and genders[idx] == 'symbol female')
            # or (actor_gendor == 'male' and genders[idx] == 'symbol male')):
            r.append(act)
            # idx = idx + 1
        if re.match(r'FC2-[\d]+', self.number, re.A) and not r:
            r = '素人'
            self.fixstudio = True
        return r

    def getOutline(self, htmltree):
        if self.morestoryline:
            from .storyline import getStoryline
            return getStoryline(self.number, self.getUncensored(htmltree),
                                proxies=self.proxies, verify=self.verify)
        return ''

    def getTrailer(self, htmltree):
        video = super().getTrailer(htmltree)
        # 加上数组判空
        if video:
            if not 'https:' in video:
                video_url = 'https:' + video
            else:
                video_url = video
        else:
            video_url = ''
        return video_url

    def getTags(self, htmltree):
        return self.getTreeAllbyExprs(htmltree, self.expr_tags, self.expr_tags2)

    def getUserRating(self, htmltree):
        try:
            numstrs = self.getTreeElement(htmltree, self.expr_userrating)
            nums = re.findall('[0-9.]+', numstrs)
            return float(nums[0])
        except:
            return ''

    def getUserVotes(self, htmltree):
        try:
            result = self.getTreeElement(htmltree, self.expr_uservotes)
            v = re.findall('[0-9.]+', result)
            return int(v[1])
        except:
            return ''

    def getaphoto(self, url, session):
        html_page = session.get(url).text
        img_url = re.findall(r'<span class\=\"avatar\" style\=\"background\-image\: url\((.*?)\)', html_page)
        return img_url[0] if img_url else ''

    def getActorPhoto(self, htmltree):
        actorall = self.getTreeAll(htmltree, self.expr_actorphoto)
        if not actorall:
            return {}
        actors = self.getActors(htmltree)
        actor_photo = {}
        for i in actorall:
            x = re.findall(r'/actors/(.*)', i.attrib['href'], re.A)
            if not len(x) or not len(x[0]) or i.text not in actors:
                continue
            # NOTE: https://c1.jdbstatic.com 会经常变动，直接使用页面内的地址获取
            # actor_id = x[0]
            # pic_url = f"https://c1.jdbstatic.com/avatars/{actor_id[:2].lower()}/{actor_id}.jpg"
            # if not self.session.head(pic_url).ok:
            try:
                pic_url = self.getaphoto(urljoin('https://javdb.com', i.attrib['href']), self.session)
                if len(pic_url):
                    actor_photo[i.text] = pic_url
            except:
                pass
        return actor_photo

