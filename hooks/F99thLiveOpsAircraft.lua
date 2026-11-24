-- F99th all-aircraft telemetry hook. Installation authorized by user.
-- Publishes active aircraft only; never changes missions or server configuration.
local hook = {}
local last = 0
local mission_script = [==[

local stamp = STAMP_PLACEHOLDER
local target = [[C:\F99th\LiveOps\telemetry\mission_aircraft.json]]

local function jquote(s)
    s = tostring(s or '')
    s = s:gsub('[%z\1-\31]', ' '):gsub('\\', '\\\\'):gsub('"', '\\"')
    return '"' .. s .. '"'
end

local function encode_unit(unit, side)
    if not unit or not unit:isExist() or not unit:isActive() then return nil end
    local group = unit:getGroup()
    if not group then return nil end
    local category = group:getCategory()
    if category ~= Group.Category.AIRPLANE and category ~= Group.Category.HELICOPTER then
        return nil
    end
    local pilot = unit:getPlayerName()
    local is_player = pilot and pilot ~= ''
    if not is_player and not unit:inAir() then return nil end
    if not is_player then pilot = unit:getName() end
    local position = unit:getPosition()
    if not position or not position.p then return nil end
    local point = position.p
    local lat, lon = coord.LOtoLL(point)
    if type(lat) ~= 'number' or type(lon) ~= 'number' then return nil end
    if math.abs(lat) > 90 or math.abs(lon) > 180 then return nil end
    local heading = 'null'
    if position.x and position.x.x and position.x.z then
        local ahead = {x=point.x+position.x.x*100, y=point.y, z=point.z+position.x.z*100}
        local lat2, lon2 = coord.LOtoLL(ahead)
        local lat1r, lat2r = math.rad(lat), math.rad(lat2)
        local delta = math.rad(lon2-lon)
        local radians = math.atan2(math.sin(delta)*math.cos(lat2r), math.cos(lat1r)*math.sin(lat2r)-math.sin(lat1r)*math.cos(lat2r)*math.cos(delta))
        heading = string.format('%.1f', (math.deg(radians) + 360) % 360)
    end
    local velocity = unit:getVelocity()
    local speed = math.sqrt(velocity.x*velocity.x+velocity.z*velocity.z)*1.943844492
    local airborne = unit:inAir() and 'true' or 'false'
    return string.format(
        '{"callsign":%s,"coalition":%s,"aircraft":%s,"lat":%.7f,"lon":%.7f,"altitude_ft":%.0f,"heading_deg":%s,"airborne":%s,"ground_speed_kt":%.1f,"is_player":%s}',
        jquote(pilot), jquote(side == 2 and 'blue' or (side == 1 and 'red' or 'neutral')), jquote(unit:getTypeName()),
        lat, lon, point.y * 3.280839895, heading, airborne, speed, is_player and 'true' or 'false'
    )
end

local ok, err = pcall(function()
    local rows = {}
    for _, side in ipairs({0, 1, 2}) do
        for _, category in ipairs({Group.Category.AIRPLANE, Group.Category.HELICOPTER}) do
            for _, group in ipairs(coalition.getGroups(side, category) or {}) do
                for _, unit in ipairs(group:getUnits() or {}) do
                    local good, row = pcall(encode_unit, unit, side)
                    if good and row then rows[#rows + 1] = row end
                end
            end
        end
    end
    local weather = env.mission.weather or {}
    local wind = weather.wind and weather.wind.atGround or {}
    local clouds = weather.clouds or {}
    local temperature = weather.season and weather.season.temperature
    local summary = string.format('%s C | wind %s m/s | clouds %s | precipitation %s',
        tostring(temperature or '?'), tostring(wind.speed or '?'),
        tostring(clouds.preset or clouds.density or '?'), ({[0]='none',[1]='rain',[2]='thunderstorm',[3]='snow',[4]='snowstorm'})[clouds.iprecptns or 0] or 'unknown')
    local mission_seconds = timer.getAbsTime() % 86400
    local file, why = io.open(target, 'wb')
    if not file then error('Unable to write mission_aircraft.json: ' .. tostring(why)) end
    file:write('{"schema_version":1,"full_scope":true,"mission":' .. jquote(MISSION_PLACEHOLDER) .. ',"stamp":' .. tostring(stamp) .. ',"mission_time_seconds":' .. tostring(mission_seconds) .. ',"weather_summary":' .. jquote(summary) .. ',"aircraft":[' .. table.concat(rows, ',') .. ']}')
    file:close()
end)
if not ok and env and env.info then
    -- Errors stay in the local DCS log; no secrets or raw data go to Discord.
    env.info('[F99th LiveOps] Position snapshot error: ' .. tostring(err))
end

]==]
function hook.onSimulationFrame()
    local now = os.time()
    if now >= last and now-last < 5 then return end
    last = now
    if not DCS.isServer() then return end
    local mission = DCS.getMissionFilename() or DCS.getMissionName() or ''
    mission = mission:gsub('\\','/'):match('([^/]+)$') or mission
    mission = mission:gsub('%.miz$', '')
    local code = mission_script:gsub('STAMP_PLACEHOLDER', function() return tostring(now) end)
    code = code:gsub('MISSION_PLACEHOLDER', function() return string.format('%q', mission) end)
    local ok, result, success = pcall(net.dostring_in, 'mission', 'a_do_script(' .. string.format('%q',code) .. ')')
    if (not ok or success == false) and net.log then net.log('[F99th Aircraft] Snapshot unavailable') end
end
DCS.setUserCallbacks(hook)

if net and net.log then net.log('[F99th Aircraft] All-aircraft hook loaded') end
