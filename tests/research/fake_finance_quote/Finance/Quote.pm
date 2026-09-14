package Finance::Quote;

# A stand-in for Finance::Quote that answers without a network, so GnuCash's
# own quote helper and wrapper run end to end. Keys are "$symbol$;$field", as
# the real module returns them; dates are mm/dd/yyyy, as the real module
# stores them.

use strict;
use warnings;

our $VERSION = '1.99';
our $AUTOLOAD;

sub new { return bless {}, shift }

sub sources { return ('alphavantage', 'currency', 'yahoo', 'yahoo_json') }

sub set_currency { return }

sub currency {
    my ($self, $from, $to) = @_;
    return 0.7331;
}

sub fetch {
    my ($self, $method, @symbols) = @_;
    my %quotes;
    for my $sym (@symbols) {
        $quotes{$sym, 'success'}  = 1;
        $quotes{$sym, 'symbol'}   = $sym;
        $quotes{$sym, 'currency'} = 'USD';
        $quotes{$sym, 'method'}   = $method;
        if ($sym eq 'AMZN') {
            $quotes{$sym, 'last'}    = 218.45;
            $quotes{$sym, 'date'}    = '01/06/2026';
            $quotes{$sym, 'isodate'} = '2026-01-06';
        }
        elsif ($sym eq 'MSFT') {
            $quotes{$sym, 'last'}    = 423.10;
            $quotes{$sym, 'date'}    = '01/06/2026';
            $quotes{$sym, 'isodate'} = '2026-01-06';
            $quotes{$sym, 'time'}    = '16:00';
        }
        else {
            $quotes{$sym, 'last'} = 190.25;
        }
    }
    return wantarray ? %quotes : \%quotes;
}

sub AUTOLOAD {
    my $name = $AUTOLOAD;
    $name =~ s/.*:://;
    return if $name eq 'DESTROY';
    return;
}

1;
