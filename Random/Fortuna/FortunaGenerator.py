# -*- coding: ascii -*-
#
#  FortunaGenerator.py : Fortuna's internal PRNG
#
# Copyright (C) 2008  Dwayne C. Litzenberger <dlitz@dlitz.net>
#
# =======================================================================
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# =======================================================================

__revision__ = "$Id$"

from Crypto.Util.python_compat import *

import struct

from Crypto.Util.number import ceil_shift, exact_log2, exact_div
from Crypto.Cipher import AES

import SHAd256

class BaseFortunaGenerator(object):
    """Abstract "generator" class for Fortuna

    The generator computes arbitrary amounts of pseudorandom data from a
    smaller amount of seed data.
    """

    # These attributes need to be set in the classes that inherit from this class

    block_size = None   # output block size in octets
    key_size = None     # key size in octets
    max_blocks_per_request = None  # Allow no more than this number of blocks per _pseudo_random_data request

    def __init__(self):
        self.counter = 0
        self.key = "\0" * self.key_size

        # Set some helper constants
        self.block_size_shift = exact_log2(self.block_size)
        assert (1 << self.block_size_shift) == self.block_size

        self.blocks_per_key = exact_div(self.key_size, self.block_size)
        assert self.key_size == self.blocks_per_key * self.block_size

        self.max_bytes_per_request = self.max_blocks_per_request * self.block_size

    def reseed(self, seed):
        self.key = SHAd256.new(self.key + seed).digest()
        self.counter += 1
        assert len(self.key) == self.key_size

    def pseudo_random_data(self, bytes):
        assert bytes >= 0

        num_full_blocks = bytes >> 20
        remainder = bytes & ((1<<20)-1)

        retval = []
        for i in xrange(num_full_blocks):
            retval.append(self._pseudo_random_data(1<<20))
        retval.append(self._pseudo_random_data(remainder))

        return "".join(retval)

    def _pseudo_random_data(self, bytes):
        if not (0 <= bytes <= self.max_bytes_per_request):
            raise AssertionError("You cannot ask for more than 1 MiB of data per request")

        num_blocks = ceil_shift(bytes, self.block_size_shift)   # num_blocks = ceil(bytes / self.block_size)

        # Compute the output
        retval = self._generate_blocks(num_blocks)[:bytes]

        # Switch to a new key to avoid later compromises of this output (i.e.
        # state compromise extension attacks)
        self.key = self._generate_blocks(self.blocks_per_key)

        assert len(retval) == bytes
        assert len(self.key) == self.key_size

        return retval

    def _generate_blocks(self, num_blocks):
        if self.counter == 0:
            raise AssertionError("generator must be seeded before use")
        assert 0 <= num_blocks <= self.max_blocks_per_request
        retval = []
        for i in xrange(num_blocks):
            retval.append(self._generate_single_block(self.counter))
            self.counter += 1
        return "".join(retval)

    def _generate_single_block(self, counter):
        raise NotImplementedError("child classes must implement this method")


class AESGenerator(BaseFortunaGenerator):
    """The standard (AES-256 based) Fortuna "generator"

    This is used internally by the Fortuna PRNG to generate arbitrary amounts
    of pseudorandom data from a smaller amount of seed data.
    """

    # We use AES using 256-bit keys
    block_size = AES.block_size
    key_size = 32

    # Because of the birthday paradox, we expect to find approximately one
    # collision for every 2**64 blocks of output from a real random source.
    # However, this code generates pseudorandom data by running AES in
    # counter mode, so there will be no collisions until the counter
    # (theoretically) wraps around at 2**128 blocks.  Thus, in order to prevent
    # Fortuna's pseudorandom output from deviating perceptibly from a true
    # random source, Ferguson and Schneier specify a limit of 2**16 blocks
    # without rekeying.
    max_blocks_per_request = 2**16

    def _generate_single_block(self, counter):
        assert counter != 0
        return AES.new(self.key, AES.MODE_ECB).encrypt(encode_counter(counter, AES.block_size))


def encode_counter(n, size):
    if not isinstance(n, (int, long)) or not isinstance(size, (int, long)):
        raise TypeError("unsupported operand type(s): %r and %r" % (type(n).__name__, type(size).__name__))

    # We support Python 2.2, so make sure we're working with long integer semantics.
    n = long(n)

    # Fortuna uses a counter >= 128 bits that theoretically could roll over
    # to zero, but would only do so after outputting 2**128 blocks.  In
    # practice, a roll-over would only happen after outputting 2**128
    # blocks.  If a computer were ever build that could do 2**128
    # operations in its lifetime, it would be very awesome, but also unwise
    # to trust this implementation as-is.  It's much more likely that a
    # zero-valued counter means that something is broken.
    if n <= 0:
        raise AssertionError("invalid Fortuna counter value: %r" % (n,))

    retval = []
    (q, r) = (size >> 2, size & 3)  # (q, r) = divmod(size, 4)
    pack = struct.pack
    for i in range(q):
        retval.append(pack("<I", n & 0xFFFFffffL))
        n >>= 32
    for i in range(r):
        retval.append(chr(n & 0xff))
        n >>= 8
    if n != 0:
        raise OverflowError("%d does not fit in %d bytes" % (n, size))
    return "".join(retval)


# vim:set ts=4 sw=4 sts=4 expandtab:
