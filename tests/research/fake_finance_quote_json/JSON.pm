package JSON;

# Only for images with JSON::PP but no JSON (arch, openSUSE), so the 5.x
# finance-quote-wrapper can print its answer.

use strict;
use warnings;
use JSON::PP ();
use Exporter 'import';

our @EXPORT = qw(encode_json decode_json);

sub encode_json { return JSON::PP::encode_json($_[0]) }
sub decode_json { return JSON::PP::decode_json($_[0]) }

1;
