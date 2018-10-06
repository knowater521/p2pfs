from abc import abstractmethod
import json
import struct
import logging
import zstandard as zstd
import asyncio
from enum import Enum, auto
logger = logging.getLogger(__name__)


class MessageType(Enum):
    REQUEST_REGISTER = auto()
    REQUEST_PUBLISH = auto()
    REQUEST_FILE_LIST = auto()
    REQUEST_FILE_LOCATION = auto()
    REQUEST_CHUNK_REGISTER = auto()
    REQUEST_LEAVE = auto()
    REPLY_REGISTER = auto()
    REPLY_FILE_LIST = auto()
    REPLY_PUBLISH = auto()
    REPLY_FILE_LOCATION = auto()
    REPLY_LEAVE = auto()
    PEER_REQUEST_CHUNK = auto()
    PEER_REPLY_CHUNK = auto()


class MessageServer:
    """ Base class for async TCP server, provides useful _read_message and _write_message methods
    for transferring message-based packets.
    """
    _SOCKET_TIMEOUT = 5

    def __init__(self, host, port, loop=None):
        self._address = (host, port)
        self._loop = loop

        self._compressor = zstd.ZstdCompressor()
        self._decompressor = zstd.ZstdDecompressor()

        # manage the connections
        self._writers = set()

    async def start(self):
        logger.info('Start listening on {}'.format(self._address))
        # start server
        await asyncio.start_server(self.__new_connection, *self._address, loop=self._loop)

    async def stop(self):
        for writer in self._writers:
            writer.close()
            await writer.wait_close()

    @staticmethod
    def __message_log(message):
        log_message = {key: message[key] for key in message if key != 'data'}
        log_message['type'] = MessageType(message['type']).name
        return log_message

    async def _read_message(self, reader):
        assert isinstance(reader, asyncio.StreamReader)
        # receive length header -> decompress (bytes) -> decode to str (str) -> json load (dict)
        raw_msg_len = await reader.readexactly(4)
        msglen = struct.unpack('>I', raw_msg_len)[0]
        raw_msg = await reader.readexactly(msglen)
        msg = json.loads(self._decompressor.decompress(raw_msg).decode('utf-8'))
        logger.debug('Message received {}'.format(self.__message_log(msg)))
        return msg

    async def _write_message(self, message, writer):
        assert isinstance(writer, asyncio.StreamWriter)
        logger.debug('Writing {}'.format(self.__message_log(message)))
        # json string (str) -> encode to utf8 (bytes) -> compress (bytes) -> add length header (bytes)
        raw_msg = json.dumps(message).encode('utf-8')
        compressed = self._compressor.compress(raw_msg)
        logger.debug('Compressed rate: {}'.format(len(compressed) / len(raw_msg)))
        compressed = struct.pack('>I', len(compressed)) + compressed
        writer.write(compressed)
        await writer.drain()

    async def __new_connection(self, reader, writer):
        self._writers.add(writer)
        await self._process_connection(reader, writer)
        self._writers.remove(writer)

    @abstractmethod
    async def _process_connection(self, reader, writer):
        raise NotImplementedError
