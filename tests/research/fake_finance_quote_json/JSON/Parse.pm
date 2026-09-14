package JSON::Parse;

# Only for images with JSON::PP but no JSON::Parse (arch, openSUSE), so the
# 5.x finance-quote-wrapper can read its request.

use strict;
use warnings;
use JSON::PP ();
use Exporter 'import';

our @EXPORT_OK = qw(valid_json parse_json);

sub valid_json {
    my ($text) = @_;
    my $ok = eval { JSON::PP->new->decode($text); 1 };
    return $ok ? 1 : 0;
}

sub parse_json { return JSON::PP->new->decode($_[0]) }

1;
