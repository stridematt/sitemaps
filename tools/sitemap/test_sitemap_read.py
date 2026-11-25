"""Run: python3 tools/sitemap/test_sitemap_read.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitemap_read as SR

SITE = 'https://www.rallytakesthetrain.com'
u = lambda p: f'<url><loc>{SITE}{p}</loc></url>'
files = {
    SITE + '/sitemap0.xml': '<urlset>' + u('/a') + u('/b') + '</urlset>',
    SITE + '/sitemap1.xml': '<urlset>' + u('/c') + '</urlset>',
    SITE + '/sitemap-new-pages.xml': '<urlset>' + u('/d') + '</urlset>',
}
index = ('<sitemapindex><sitemap><loc>sitemap0.xml</loc></sitemap><sitemap><loc>https://rallytakesthetrain.com/sitemap1.xml</loc></sitemap>'
         '<sitemap><loc>https://www.rallytakesthetrain.com/sitemap-new-pages.xml</loc></sitemap><sitemap><loc>/not-a-sitemap.html</loc></sitemap></sitemapindex>')
asked = []
def fetch(x):
    asked.append(x)
    return files.get(x)

out = SR.expand(index, SITE + '/sitemap.xml', fetch)
assert [l for l in __import__('re').findall(r'<loc>([^<]*)</loc>', out)] == [SITE + '/a', SITE + '/b', SITE + '/c', SITE + '/d'], out
assert asked == [SITE + '/sitemap0.xml', SITE + '/sitemap1.xml', SITE + '/sitemap-new-pages.xml'], asked
assert SR.expand(index.encode(), SITE + '/sitemap.xml', lambda x: files[x].encode()).startswith(b'<urlset>'), 'bytes in, bytes out'
assert SR.expand('<urlset>' + u('/z') + '</urlset>', SITE + '/sitemap.xml', fetch).endswith('</urlset>'), 'single file unchanged'
assert SR.files(index, 'https://rally-takes-the-train-site.squarespace.com/sitemap.xml')[0] == 'https://rally-takes-the-train-site.squarespace.com/sitemap0.xml'
try:
    SR.expand(index, SITE + '/sitemap.xml', lambda x: None if x.endswith('sitemap1.xml') else files[x]); raise SystemExit('should fail')
except RuntimeError as e:
    assert 'sitemap1.xml' in str(e)
print('sitemap_read tests passed')
