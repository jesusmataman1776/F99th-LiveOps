-- F99th LiveOps Status hook v0.1 -- ADDITIONAL hook, does not replace roster hook.
-- Install in Saved Games\DCS.dcs_serverrelease\Scripts\Hooks\F99thLiveOpsStatus.lua
-- Exports ONLY mission filename, mission state, elapsed wall time and player count.
-- Writes locally; does not open ports or change SRS, DCSServerBot, or missions.

local hook = {}
local target = [[C:\F99th\LiveOps\telemetry\server_status.json]]
local server_name = 'F99th3'
local refresh_seconds = 5
local last_tick = 0
local last_warning = 0
local sim_started_at = nil
local mission_loaded = false
local loading = false
local mission_name = nil

local function warning(message)
    local now = os.time()
    if now < last_warning or now - last_warning >= 60 then
        last_warning = now
        if net and net.log then net.log('[F99th LiveOps Status] ' .. tostring(message)) end
    end
end

local function safe_call(fn)
    if type(fn) ~= 'function' then return nil end
    local ok, result = pcall(fn)
    if ok then return result end
    return nil
end

local function valid_mission_name(raw)
    if type(raw) ~= 'string' or raw == '' then return nil end
    local cleaned = raw:gsub('\\', '/')
    local filename = cleaned:match('([^/]+)$') or cleaned
    filename = filename:gsub('%.miz$', '')
    filename = filename:gsub('^%s+', ''):gsub('%s+$', '')
    if filename == '' or filename:lower() == 'tempmission' then return nil end
    if #filename > 120 then filename = filename:sub(1, 120) end
    return filename
end

local function get_mission_name()
    -- Prefer the file actually loaded; getMissionName may return tempMission on some DCS builds.
    local name = valid_mission_name(safe_call(DCS.getMissionFilename))
    if name then return name end
    name = valid_mission_name(safe_call(DCS.getMissionName))
    if name then return name end
    -- Fallback to the separate DCS mission Lua environment (no files modified).
    if net and type(net.dostring_in) == 'function' then
        local ok, result = pcall(net.dostring_in, 'mission',
            'return env and env.getMissionName and env.getMissionName() or ""')
        if ok then return valid_mission_name(result) end
    end
    return nil
end

local function connected_count()
    local players = safe_call(net.get_player_list)
    if type(players) ~= 'table' then return nil end
    local count = 0
    for _, id in pairs(players) do
        if tonumber(id) and tonumber(id) > 1 then count = count + 1 end
    end
    return count
end

local function publish()
    if not DCS.isServer() then return end
    local now = os.time()
    if mission_loaded and not mission_name then mission_name = get_mission_name() end
    local state = loading and 'Loading' or 'Stopped'
    if mission_loaded then
        state = safe_call(DCS.getPause) == true and 'Paused' or 'Running'
    end
    local elapsed = sim_started_at and math.max(0, now - sim_started_at) or nil
    local payload = {
        server = server_name,
        mission = mission_loaded and mission_name or nil,
        mission_state = state,
        mission_elapsed_seconds = elapsed,
        connected_players = connected_count(),
        stamp = now,
    }
    local json = net.lua2json(payload)
    local file, err = io.open(target, 'wb')
    if not file then error('Unable to write server_status.json: ' .. tostring(err)) end
    file:write(json)
    file:close()
end

function hook.onMissionLoadBegin()
    loading = true
    mission_loaded = false
    mission_name = nil
    sim_started_at = nil
end

function hook.onMissionLoadEnd()
    mission_name = get_mission_name()
end

function hook.onSimulationStart()
    loading = false
    mission_loaded = true
    sim_started_at = os.time()
    mission_name = get_mission_name() or mission_name
end

function hook.onSimulationStop()
    loading = false
    mission_loaded = false
    sim_started_at = nil
    mission_name = nil
end

function hook.onSimulationFrame()
    local now = os.time()
    if now < last_tick or now - last_tick >= refresh_seconds then
        last_tick = now
        local ok, err = pcall(publish)
        if not ok then warning(err) end
    end
end

DCS.setUserCallbacks(hook)
if net and net.log then net.log('[F99th LiveOps Status] hook v0.1 loaded') end
