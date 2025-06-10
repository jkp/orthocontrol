# OrthoControl Design Decisions and Learnings

## The Challenge

The Ortho Remote MIDI controller sends continuous CC (Control Change) messages when the knob is turned - often 20-50 messages per second during normal turning. We need to translate these into Spotify volume changes without overwhelming the API.

## What We've Learned

### 1. Spotify API Rate Limits
- **Rate limit appears to be ~180 requests/minute (3/second)** based on documentation
- **In practice, we hit limits after ~20 rapid calls** - suggesting burst limits
- **HTTP 429 responses cascade** - retry logic can make things worse
- **Rate limits are device/app specific** - not just per user

### 2. MIDI Message Patterns
- **Ortho Remote floods messages** - even small movements generate many CC events
- **Values are absolute, not relative** - each message contains the full position (0-127)
- **Messages arrive in bursts** - not evenly spaced
- **Final position matters most** - intermediate values during turning are less important

### 3. User Experience Requirements
- **Responsiveness is key** - lag feels bad, especially on first movement
- **Final position accuracy** - where you stop should be where the volume lands
- **Smooth during movement** - not too jumpy or delayed
- **No surprising jumps** - hence the latching mechanism

## Approaches We've Tried

### 1. Throttle/Debounce Decorator (Original)
- Used complex throttling with backoff
- Problem: Still processed too many messages, felt sluggish

### 2. Background Thread with Instant Updates
- Separate thread for API calls, instant target updates
- Better responsiveness but still hit rate limits

### 3. Progressive Backoff
- Start fast (10ms), back off to slower rates
- Helped but not enough to avoid rate limits

### 4. Settling Detection
- Try to detect when knob stops moving
- Issues: Multiple settle events, timing conflicts

## The Core Tradeoffs

1. **Responsiveness vs Rate Limits**
   - Faster updates = better feel but more API calls
   - Slower updates = respect limits but feels laggy

2. **Continuous Updates vs Final Position**
   - Continuous = smooth visual feedback
   - Final only = fewer calls but no feedback during movement

3. **Complexity vs Reliability**
   - Complex timing = tries to optimize everything
   - Simple = predictable but maybe not optimal

## Real-World Findings (June 2025)

After extensive testing, we discovered:

1. **Spotify's rate limit is more aggressive than documented**
   - Hit 429 errors after ~20-30 calls in quick succession
   - Suggests burst detection, not just requests/minute
   - Spotipy's automatic retry makes it worse (compounds the problem)

2. **Human perception vs API limits**
   - 500ms delay feels sluggish for volume control
   - 100ms feels responsive but risks rate limits
   - Users expect immediate feedback when turning a knob

3. **Settling detection is problematic**
   - Multiple "settled" events fire for one knob movement
   - Timer-based detection conflicts with continuous updates
   - Force-sync flags create race conditions

## Final Recommended Approach

Based on our learnings, the simplest reliable approach is:

1. **Disable Spotipy auto-retry** - Handle 429s ourselves
2. **Fixed 250ms sync interval** - Compromise between UX and safety
3. **Local feedback** - Show target volume immediately in logs
4. **Single settling detection** - 400ms after last MIDI = final sync
5. **Hard backoff on 429** - 10 seconds to let limits reset

## Implementation Guidelines

1. **Maximum 4 API calls per second** - But back off immediately on 429
2. **Log target vs actual volume** - Users see immediate feedback
3. **Consider alternatives** - Spotify API may not be ideal for real-time control
4. **Keep it simple** - Complex timing strategies are hard to debug

## Alternative Approaches to Consider

1. **Local volume proxy** - Control system volume, let Spotify follow
2. **Batch updates** - Collect changes, send periodically
3. **Different API** - Apple Music API might have different limits
4. **Hardware solution** - USB HID volume control instead of MIDI