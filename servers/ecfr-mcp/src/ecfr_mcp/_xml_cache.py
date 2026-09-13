"""Bounded five-minute cache of public, dated eCFR XML, with miss coalescing."""
from collections import OrderedDict
import time
import xml.etree.ElementTree as ET
from ._pacing import _process_lock


class XmlCache:
    def __init__(self, *, ttl=300, max_entries=128, max_bytes=32*1024*1024,
                 max_entry_bytes=2*1024*1024, clock=time.monotonic):
        self.ttl=ttl
        self.max_entries=max_entries
        self.max_bytes=max_bytes
        self.max_entry_bytes=max_entry_bytes
        self.clock=clock
        self.entries=OrderedDict()
        self.bytes=0

    def _get(self, key):
        now=self.clock()
        for expired in [k for k,(expiry,_,_) in self.entries.items() if expiry<=now]:
            self.bytes-=self.entries.pop(expired)[2]
        if key not in self.entries:
            return None
        self.entries.move_to_end(key)
        return self.entries[key][1]

    async def get_or_fetch(self, key, fetch):
        found=self._get(key)
        if found is not None:
            return found
        # XML misses are already serialized upstream. One same-loop lock also
        # coalesces duplicate misses without an unbounded per-query lock map.
        async with _process_lock(f"ecfr-xml-cache:{id(self)}"):
            found=self._get(key)
            if found is not None:
                return found
            value=await fetch()  # Errors/cancellation never populate the cache.
            size=len(value.encode('utf-8'))
            if size>min(self.max_entry_bytes,self.max_bytes) or self.max_entries<1:
                return value
            try:
                ET.fromstring(value)
            except ET.ParseError:
                return value
            while self.entries and (len(self.entries)>=self.max_entries or self.bytes+size>self.max_bytes):
                _,old=self.entries.popitem(last=False)
                self.bytes-=old[2]
            self.entries[key]=(self.clock()+self.ttl,value,size)
            self.bytes+=size
            return value
