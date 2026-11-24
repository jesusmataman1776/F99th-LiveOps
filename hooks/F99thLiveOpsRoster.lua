-- F99th Live Operations - pilot roster + live aircraft position probe (v0.2)
-- Replace the earlier Hooks/F99thLiveOpsRoster.lua with this file.
-- Requires C:\F99th\LiveOps\telemetry and your existing working MissionScripting.lua.
-- Does not modify DCSServerBot, SRS, LotAtc, Export.lua, or any mission file.
-- Writes connected human pilots to pilots.json; aircraft details are read from
-- a short-lived mission snapshot created through the DCS scripting API.
-- No IPs, UCIDs, passwords, AI aircraft, or server commands appear in the feed.
-- Keep the Flask dashboard listening only on 127.0.0.1 until authenticated.

local hook = {}
local directory = [[C:\F99th\LiveOps\telemetry\]]
local roster_path = directory .. 'pilots.json'
local aircraft_path = directory .. 'aircraft.json'
local poll_seconds = 5
local last_tick = 0
local last_warning = 0

local function warn_once_per_minute(text)
    local now = os.time()
    if now < last_warning or now - last_warning >= 60 then
        last_warning = now
        if net and net.log then
            net.log('[F99th LiveOps] ' .. tostring(text))
        end
    end
end

-- Runs INSIDE DCS mission scripting. It writes ONLY human-crewed aircraft
-- position records; no return-value transfer between Lua states is needed.
-- The long string is never evaluated from an external user request.
local mission_script = [==[
local stamp = STAMP_PLACEHOLDER
local target = [[C:\F99th\LiveOps\telemetry\aircraft.json]]

local function jquote(s)
    s = tostring(s or '')
    s = s:gsub('[%z\1-\31]', ' '):gsub('\\', '\\\\'):gsub('"', '\\"')
    return '"' .. s .. '"'
end

local function encode_unit(unit, side)
    if not unit or not unit:isExist() then return nil end
    local group = unit:getGroup()
    if not group then return nil end
    local category = group:getCategory()
    if category ~= Group.Category.AIRPLANE and category ~= Group.Category.HELICOPTER then
        return nil
    end
    local pilot = unit:getPlayerName()
    if not pilot or pilot == '' then return nil end
    local position = unit:getPosition()
    if not position or not position.p then return nil end
    local point = position.p
    local lat, lon = coord.LOtoLL(point)
    if type(lat) ~= 'number' or type(lon) ~= 'number' then return nil end
    if math.abs(lat) > 90 or math.abs(lon) > 180 then return nil end
    local heading = 'null'
    if position.x and position.x.x and position.x.z then
        local radians = math.atan2(position.x.x, position.x.z)
        heading = string.format('%.1f', (math.deg(radians) + 360) % 360)
    end
    local airborne = unit:inAir() and 'true' or 'false'
    return string.format(
        '{"callsign":%s,"coalition":%s,"aircraft":%s,"lat":%.7f,"lon":%.7f,"altitude_ft":%.0f,"heading_deg":%s,"airborne":%s}',
        jquote(pilot), jquote(side == 2 and 'blue' or 'red'), jquote(unit:getTypeName()),
        lat, lon, point.y * 3.280839895, heading, airborne
    )
end

local ok, err = pcall(function()
    local rows = {}
    for _, side in ipairs({1, 2}) do
        for _, unit in ipairs(coalition.getPlayers(side) or {}) do
            local good, row = pcall(encode_unit, unit, side)
            if good and row then rows[#rows + 1] = row end
        end
    end
    local file, why = io.open(target, 'wb')
    if not file then error('Unable to write aircraft.json: ' .. tostring(why)) end
    file:write('{"stamp":' .. tostring(stamp) .. ',"aircraft":[' .. table.concat(rows, ',') .. ']}')
    file:close()
end)
if not ok and env and env.info then
    -- Errors stay in the local DCS log; no secrets or raw data go to Discord.
    env.info('[F99th LiveOps] Position snapshot error: ' .. tostring(err))
end
]==]

local function get_positions(now)
    local mission_code = mission_script:gsub('STAMP_PLACEHOLDER', tostring(now))
    local command = 'a_do_script(' .. string.format('%q', mission_code) .. ')'
    -- The mission state might be unavailable during a mission transition.
    local ok, result, success = pcall(net.dostring_in, 'mission', command)
    if not ok or success == false then
        warn_once_per_minute('Mission snapshot not available: ' .. tostring(result))
        return nil
    end

    local file = io.open(aircraft_path, 'rb')
    if not file then return nil end
    local raw = file:read('*a')
    file:close()
    local parsed_ok, parsed = pcall(net.json2lua, raw)
    -- Check the timestamp to prevent publishing stale coordinates.
    if not parsed_ok or type(parsed) ~= 'table' or tonumber(parsed.stamp) ~= now then
        return nil
    end
    if type(parsed.aircraft) ~= 'table' then return nil end
    local by_name = {}
    for _, plane in pairs(parsed.aircraft) do
        if type(plane) == 'table' then
            local key = tostring(plane.callsign or '') .. '\n' .. tostring(plane.coalition or '')
            -- Identical pilot names on the same coalition must not be mismatched.
            if by_name[key] == nil then by_name[key] = plane else by_name[key] = false end
        end
    end
    return by_name
end

local function build_roster(positions)
    local json_rows = {}
    for _, player_id in pairs(net.get_player_list() or {}) do
        -- DCS dedicated-server host placeholder is player ID 1.
        if tonumber(player_id) and tonumber(player_id) > 1 then
            local info = net.get_player_info(player_id)
            if type(info) == 'table' then
                local side = tonumber(info.side) or 0
                local coalition = (side == 2 and 'blue') or (side == 1 and 'red') or 'neutral'
                local callsign = tostring(info.name or 'Unknown pilot')
                local row = {callsign = callsign, coalition = coalition, aircraft = ''}
                if info.slot and DCS.getUnitType then
                    local ok, aircraft_type = pcall(DCS.getUnitType, info.slot)
                    if ok and type(aircraft_type) == 'string' then
                        row.aircraft = aircraft_type
                    end
                end
                local position = positions and positions[callsign .. '\n' .. coalition]
                if type(position) == 'table' then
                    row.aircraft = tostring(position.aircraft or row.aircraft)
                    row.lat = position.lat
                    row.lon = position.lon
                    row.altitude_ft = position.altitude_ft
                    row.heading_deg = position.heading_deg
                    if position.airborne == false then
                        row.aircraft = row.aircraft .. ' (On ground)'
                    end
                end
                json_rows[#json_rows + 1] = net.lua2json(row)
            end
        end
    end
    return '{"pilots":[' .. table.concat(json_rows, ',') .. ']}'
end

local function collect()
    if not DCS.isServer() then return end
    local now = os.time()
    local positions = get_positions(now)
    local payload = build_roster(positions)
    local file, why = io.open(roster_path, 'wb')
    if not file then error('Cannot open pilots.json: ' .. tostring(why)) end
    local saved, error_text = file:write(payload)
    file:close()
    if not saved then error('Cannot write pilots.json: ' .. tostring(error_text)) end
end

function hook.onSimulationFrame()
    local now = os.time()
    if now < last_tick or now - last_tick >= poll_seconds then
        last_tick = now
        local ok, err = pcall(collect)
        if not ok then warn_once_per_minute('Telemetry error: ' .. tostring(err)) end
    end
end

DCS.setUserCallbacks(hook)
if net and net.log then
    net.log('[F99th LiveOps] Roster + aircraft hook v0.2 loaded')
end
