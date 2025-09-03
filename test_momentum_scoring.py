#!/usr/bin/env python3

# Test momentum scoring for LONG vs SHORT
print("Testing momentum scoring...")

# Simulate momentum values
momentum_positive = 0.05  # 5% positive momentum
momentum_negative = -0.05  # 5% negative momentum

print(f"Original momentum (positive): {momentum_positive}")
print(f"Original momentum (negative): {momentum_negative}")

# Test LONG scoring (should favor positive momentum)
momentumScore_long_pos = momentum_positive if 'long' == 'long' else -momentum_positive
momentumScore_long_neg = momentum_negative if 'long' == 'long' else -momentum_negative

print(f"LONG with positive momentum: {max(momentumScore_long_pos, 0)}")
print(f"LONG with negative momentum: {max(momentumScore_long_neg, 0)}")

# Test SHORT scoring (should favor negative momentum)
momentumScore_short_pos = momentum_positive if 'short' == 'long' else -momentum_positive
momentumScore_short_neg = momentum_negative if 'short' == 'long' else -momentum_negative

print(f"SHORT with positive momentum: {max(momentumScore_short_pos, 0)}")
print(f"SHORT with negative momentum: {max(momentumScore_short_neg, 0)}")

print("\nCorrect behavior:")
print("- LONG should score higher with positive momentum")
print("- SHORT should score higher with negative momentum")
print("- This allows both types to compete fairly based on market direction")
