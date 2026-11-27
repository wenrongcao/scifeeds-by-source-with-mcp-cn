import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_feeds_server import parse_feed, parse_opml


class ParseOpmlTests(unittest.TestCase):
    def test_reads_all_feed_entries_and_preserves_ampersands_in_urls(self):
        opml = b'''<?xml version="1.0"?>
        <opml version="2.0"><body>
          <outline title="Earth" type="rss" xmlUrl="https://example.org/rss?a=1&amp;b=2" htmlUrl="https://example.org" />
          <outline text="Folder"><outline text="Blog" xmlUrl="https://blog.example/feed" /></outline>
          <outline text="Not a feed" />
        </body></opml>'''

        feeds = parse_opml(opml)

        self.assertEqual(len(feeds), 2)
        self.assertEqual(feeds[0]["title"], "Earth")
        self.assertEqual(feeds[0]["url"], "https://example.org/rss?a=1&b=2")
        self.assertEqual(feeds[0]["site_url"], "https://example.org")
        self.assertEqual(feeds[1]["title"], "Blog")

    def test_parses_rss_entry_fields(self):
        xml = b'''<rss version="2.0"><channel><item>
          <title>New paper</title><link>https://example.org/paper</link>
          <pubDate>Mon, 02 Nov 2026 12:00:00 GMT</pubDate>
          <description>A short abstract.</description>
        </item></channel></rss>'''

        entries = parse_feed(xml, "Earth Journal")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["feed_title"], "Earth Journal")
        self.assertEqual(entries[0]["title"], "New paper")
        self.assertEqual(entries[0]["link"], "https://example.org/paper")
        self.assertEqual(entries[0]["published"], "2026-11-02T12:00:00+00:00")
        self.assertEqual(entries[0]["summary"], "A short abstract.")

    def test_atom_parsing_uses_alternate_link_and_updated_date(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>Atom update</title><id>tag:example.org,2026:item</id>
          <updated>2026-11-03T09:30:00Z</updated>
          <link rel="alternate" href="https://example.org/atom" />
          <summary>Atom summary</summary>
        </entry></feed>'''

        entries = parse_feed(xml, "Atom Journal")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Atom update")
        self.assertEqual(entries[0]["link"], "https://example.org/atom")
        self.assertEqual(entries[0]["published"], "2026-11-03T09:30:00+00:00")
        self.assertEqual(entries[0]["summary"], "Atom summary")


class McpProtocolTests(unittest.TestCase):
    def test_list_feeds_returns_mcp_valid_structured_object(self):
        from sci_feeds_server import handle_request, load_feeds
        from unittest.mock import patch
        feeds = [{"title": "Example", "url": "https://example.org/rss", "site_url": "https://example.org"}]
        with patch('sci_feeds_server.load_feeds', return_value=feeds):
            result = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "list_feeds", "arguments": {}}})['result']
        self.assertIsInstance(result['structuredContent'], dict)
        self.assertEqual(result['structuredContent']['feeds'], feeds)
        self.assertEqual(result['structuredContent']['feed_count'], len(feeds))
        self.assertFalse(result['isError'])

    def test_fetch_defaults_to_100_and_accepts_100_entries_per_source(self):
        from datetime import datetime, timezone
        from io import BytesIO
        from unittest.mock import patch
        from sci_feeds_server import handle_request

        pub_date = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
        items = ''.join(
            f'<item><title>Entry {i}</title><link>https://example.org/{i}</link>'
            f'<pubDate>{pub_date}</pubDate></item>' for i in range(110)
        )
        feed = f'<rss><channel>{items}</channel></rss>'.encode()
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "fetch_recent_entries", "arguments": {}}}
        feed_list = [{"title": "Example", "url": "https://example.org/rss"}]
        with patch('sci_feeds_server.load_feeds', return_value=feed_list), \
             patch('sci_feeds_server.urllib.request.urlopen', side_effect=lambda *a, **kw: BytesIO(feed)):
            result = handle_request(request)['result']
            self.assertFalse(result['isError'])
            self.assertEqual(result['structuredContent']['entry_count'], 100)
            request['params']['arguments']['max_per_feed'] = 100
            result = handle_request(request)['result']
            self.assertFalse(result['isError'])
            self.assertEqual(result['structuredContent']['entry_count'], 100)
            request['params']['arguments']['max_per_feed'] = 101
            self.assertTrue(handle_request(request)['result']['isError'])
        tools = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})['result']['tools']
        schema = next(t for t in tools if t['name'] == 'fetch_recent_entries')['inputSchema']['properties']['max_per_feed']
        self.assertEqual(schema['maximum'], 100)

    def test_initialize_returns_mcp_capabilities(self):
        from sci_feeds_server import handle_request

        response = handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        })

        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_tools_list_exposes_only_read_only_feed_tools(self):
        from sci_feeds_server import handle_request

        response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        tools = response["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["list_feeds", "fetch_recent_entries"])
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in tools))

    def test_notifications_do_not_return_json_rpc_responses(self):
        from sci_feeds_server import handle_request

        response = handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})

        self.assertIsNone(response)


if __name__ == "__main__":
    unittest.main()
