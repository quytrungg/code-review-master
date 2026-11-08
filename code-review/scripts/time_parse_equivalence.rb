#!/usr/bin/env ruby
# frozen_string_literal: true

# Settles a "this matches the internal serializer" claim about a timestamp field.
#
# Compares the two idioms a port usually swaps between:
#   A: Time.zone.parse(raw).to_datetime.rfc3339          (wall clock read in Time.zone)
#   B: Time.parse(raw).in_time_zone.to_datetime.rfc3339  (wall clock read in the process zone)
#
# They agree for every string carrying an explicit offset and diverge for a naive one.
#
# usage:
#   rbenv exec ruby scripts/time_parse_equivalence.rb "2026-06-25T17:19:48+10:00" "2026-06-25 17:19:48"
#
# Pick the activesupport the lockfile pins, when the bundle is not installed:
#   ACTIVESUPPORT_VERSION=7.2.3 rbenv exec ruby scripts/time_parse_equivalence.rb ...

version = ENV["ACTIVESUPPORT_VERSION"].to_s
begin
  gem "activesupport", version unless version.empty?
  require "active_support/all"
rescue LoadError
  warn "activesupport is not loadable. Re-run with ACTIVESUPPORT_VERSION set to the version in Gemfile.lock."
  exit 1
end

ZONES = %w[Australia/Sydney Europe/London UTC America/New_York].freeze

samples = ARGV.empty? ? ["2026-06-25T17:19:48+10:00"] : ARGV

def attempt
  yield
rescue StandardError => e
  "RAISE:#{e.class}"
end

puts format("%-18s %-32s %-34s %-34s %s", "zone", "raw", "Time.zone.parse", "Time.parse.in_time_zone", "verdict")

divergent = 0

ZONES.each do |zone|
  Time.zone = zone
  samples.each do |raw|
    a = attempt { Time.zone.parse(raw)&.to_datetime&.rfc3339 }
    b = attempt { Time.parse(raw).in_time_zone.to_datetime.rfc3339 }
    same = a == b
    divergent += 1 unless same
    puts format("%-18s %-32s %-34s %-34s %s", zone, raw.inspect, a.inspect, b.inspect, same ? "SAME" : "DIFF")
  end
end

# A DIFF on a form the writer never stores is a question, not a finding. Check the writer
# before reporting: a TimeWithZone assignment serialises with an offset and never diverges.
puts
puts divergent.zero? ? "No divergence on these samples." : "#{divergent} divergent sample(s); confirm the writer cannot produce that form before reporting."
