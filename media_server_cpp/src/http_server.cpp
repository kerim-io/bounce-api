#include "http_server.h"
#include "room_manager.h"
#include "streaming_server.h"
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <cerrno>
#include <iostream>
#include <sstream>
#include <cstring>
#include <vector>

namespace onlylang {

HttpServer::HttpServer(const std::string& host, int port,
                       std::shared_ptr<RoomManager> room_manager,
                       std::shared_ptr<StreamingServer> streaming_server)
    : host_(host),
      port_(port),
      running_(false),
      room_manager_(room_manager),
      streaming_server_(streaming_server),
      server_socket_(-1) {
}

HttpServer::~HttpServer() {
    stop();
}

bool HttpServer::start() {
    if (running_) {
        return true;
    }

    server_socket_ = socket(AF_INET, SOCK_STREAM, 0);
    if (server_socket_ < 0) {
        std::cerr << "Failed to create socket" << std::endl;
        return false;
    }

    int opt = 1;
    if (setsockopt(server_socket_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
        std::cerr << "Failed to set socket options" << std::endl;
        close(server_socket_);
        return false;
    }

    struct sockaddr_in address;
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(port_);

    if (bind(server_socket_, (struct sockaddr*)&address, sizeof(address)) < 0) {
        std::cerr << "Failed to bind socket to port " << port_ << std::endl;
        close(server_socket_);
        return false;
    }

    if (listen(server_socket_, 10) < 0) {
        std::cerr << "Failed to listen on socket" << std::endl;
        close(server_socket_);
        return false;
    }

    setup_routes();
    running_ = true;

    accept_thread_ = std::thread(&HttpServer::accept_connections, this);

    std::cout << "HTTP server listening on " << host_ << ":" << port_ << std::endl;
    return true;
}

void HttpServer::stop() {
    if (!running_) {
        return;
    }

    running_ = false;

    if (server_socket_ >= 0) {
        close(server_socket_);
        server_socket_ = -1;
    }

    if (accept_thread_.joinable()) {
        accept_thread_.join();
    }

    std::cout << "HTTP server stopped" << std::endl;
}

void HttpServer::register_route(const std::string& method, const std::string& path, RouteHandler handler) {
    routes_[method][path] = handler;
}

void HttpServer::setup_routes() {
    register_route("POST", "/room/create", [this](const HttpRequest& req) {
        return handle_create_room(req);
    });

    register_route("POST", "/room/:room_id/stop", [this](const HttpRequest& req) {
        return handle_delete_room(req);
    });

    register_route("GET", "/room/:room_id/stats", [this](const HttpRequest& req) {
        return handle_get_room_stats(req);
    });

    register_route("GET", "/stats", [this](const HttpRequest& req) {
        return handle_get_server_stats(req);
    });

    register_route("GET", "/health", [this](const HttpRequest& req) {
        return handle_health_check(req);
    });
}

void HttpServer::accept_connections() {
    while (running_) {
        struct sockaddr_in client_address;
        socklen_t client_len = sizeof(client_address);

        int client_socket = accept(server_socket_, (struct sockaddr*)&client_address, &client_len);

        if (client_socket < 0) {
            if (running_) {
                std::cerr << "Failed to accept connection" << std::endl;
            }
            continue;
        }

        std::thread(&HttpServer::handle_client, this, client_socket).detach();
    }
}

void HttpServer::handle_client(int client_socket) {
    try {
        // Set socket timeout to prevent slowloris attacks
        struct timeval tv;
        tv.tv_sec = 30;  // 30 second timeout
        tv.tv_usec = 0;
        setsockopt(client_socket, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

        constexpr size_t MAX_REQUEST_SIZE = 8192;
        std::vector<char> buffer(MAX_REQUEST_SIZE);
        ssize_t bytes_read = read(client_socket, buffer.data(), buffer.size() - 1);

        if (bytes_read < 0) {
            std::cerr << "Error reading from socket: " << strerror(errno) << std::endl;
            close(client_socket);
            return;
        }

        if (bytes_read == 0) {
            close(client_socket);
            return;
        }

        buffer[bytes_read] = '\0';
        std::string raw_request(buffer.data(), bytes_read);

        HttpRequest request = parse_request(raw_request);

        RouteHandler handler;
        std::map<std::string, std::string> params;

        HttpResponse response;

        if (match_route(request.method, request.path, handler, params)) {
            request.path_params = params;
            response = handler(request);
        } else {
            response.status_code = 404;
            response.set_error(404, "Route not found");
        }

        std::string response_str = build_response(response);
        ssize_t bytes_written = write(client_socket, response_str.c_str(), response_str.length());

        if (bytes_written < 0) {
            std::cerr << "Error writing to socket: " << strerror(errno) << std::endl;
        }

        close(client_socket);
    } catch (const std::exception& e) {
        std::cerr << "Exception in handle_client: " << e.what() << std::endl;
        close(client_socket);
    } catch (...) {
        std::cerr << "Unknown exception in handle_client" << std::endl;
        close(client_socket);
    }
}

HttpRequest HttpServer::parse_request(const std::string& raw_request) {
    HttpRequest request;

    std::istringstream stream(raw_request);
    std::string line;

    if (std::getline(stream, line)) {
        std::istringstream line_stream(line);
        std::string path_query;
        line_stream >> request.method >> path_query;

        size_t query_pos = path_query.find('?');
        if (query_pos != std::string::npos) {
            request.path = path_query.substr(0, query_pos);
            std::string query = path_query.substr(query_pos + 1);
        } else {
            request.path = path_query;
        }
    }

    while (std::getline(stream, line) && line != "\r") {
        size_t colon_pos = line.find(':');
        if (colon_pos != std::string::npos && colon_pos + 2 < line.length()) {
            std::string key = line.substr(0, colon_pos);
            std::string value = line.substr(colon_pos + 2);
            if (!value.empty() && value.back() == '\r') {
                value.pop_back();
            }
            request.headers[key] = value;
        }
    }

    std::string remaining;
    while (std::getline(stream, line)) {
        remaining += line + "\n";
    }
    request.body = remaining;

    return request;
}

std::string HttpServer::build_response(const HttpResponse& response) {
    std::ostringstream oss;

    oss << "HTTP/1.1 " << response.status_code << " ";

    switch (response.status_code) {
        case 200: oss << "OK"; break;
        case 201: oss << "Created"; break;
        case 400: oss << "Bad Request"; break;
        case 404: oss << "Not Found"; break;
        case 500: oss << "Internal Server Error"; break;
        default: oss << "Unknown"; break;
    }

    oss << "\r\n";

    for (const auto& [key, value] : response.headers) {
        oss << key << ": " << value << "\r\n";
    }

    oss << "Content-Length: " << response.body.length() << "\r\n";
    oss << "Connection: close\r\n";
    oss << "\r\n";
    oss << response.body;

    return oss.str();
}

bool HttpServer::match_route(const std::string& method, const std::string& path,
                             RouteHandler& handler, std::map<std::string, std::string>& params) {
    auto method_routes = routes_.find(method);
    if (method_routes == routes_.end()) {
        return false;
    }

    // FIRST PASS: Check exact routes (no parameters)
    for (const auto& [pattern, route_handler] : method_routes->second) {
        if (pattern.find(':') == std::string::npos) {
            if (pattern == path) {
                handler = route_handler;
                return true;
            }
        }
    }

    // SECOND PASS: Check parametrized routes
    for (const auto& [pattern, route_handler] : method_routes->second) {
        if (pattern.find(':') != std::string::npos) {
            // Clear params for this attempt
            params.clear();

            std::istringstream pattern_stream(pattern);
            std::istringstream path_stream(path);
            std::string pattern_part, path_part;
            bool match = true;

            while (std::getline(pattern_stream, pattern_part, '/') &&
                   std::getline(path_stream, path_part, '/')) {
                if (pattern_part.empty() && path_part.empty()) continue;

                if (!pattern_part.empty() && pattern_part[0] == ':') {
                    std::string param_name = pattern_part.substr(1);
                    params[param_name] = path_part;
                } else if (pattern_part != path_part) {
                    match = false;
                    break;
                }
            }

            // Both streams must be exhausted for a match
            if (match && !std::getline(pattern_stream, pattern_part, '/') &&
                !std::getline(path_stream, path_part, '/')) {
                handler = route_handler;
                return true;
            }
        }
    }

    return false;
}

HttpResponse HttpServer::handle_create_room(const HttpRequest& req) {
    HttpResponse response;

    std::string post_id;
    std::string host_user_id;

    // Parse post_id (also accept classroom_id for backwards compatibility)
    size_t post_pos = req.body.find("\"post_id\":\"");
    size_t classroom_pos = req.body.find("\"classroom_id\":\"");

    if (post_pos != std::string::npos) {
        size_t start = post_pos + 11;
        if (start < req.body.length()) {
            size_t end = req.body.find("\"", start);
            if (end != std::string::npos && end > start) {
                post_id = req.body.substr(start, end - start);
                if (post_id.length() > 256) {
                    response.set_error(400, "post_id too long");
                    return response;
                }
            }
        }
    } else if (classroom_pos != std::string::npos) {
        // Backwards compatibility with classroom_id
        size_t start = classroom_pos + 16;
        if (start < req.body.length()) {
            size_t end = req.body.find("\"", start);
            if (end != std::string::npos && end > start) {
                post_id = req.body.substr(start, end - start);
                if (post_id.length() > 256) {
                    response.set_error(400, "post_id too long");
                    return response;
                }
            }
        }
    }

    // Parse host_user_id with bounds checking
    size_t host_pos = req.body.find("\"host_user_id\":\"");
    if (host_pos != std::string::npos) {
        size_t start = host_pos + 16;
        if (start < req.body.length()) {
            size_t end = req.body.find("\"", start);
            if (end != std::string::npos && end > start) {
                host_user_id = req.body.substr(start, end - start);
                // Limit length to prevent DoS
                if (host_user_id.length() > 256) {
                    response.set_error(400, "host_user_id too long");
                    return response;
                }
            }
        }
    }

    if (post_id.empty() || host_user_id.empty()) {
        response.set_error(400, "Missing post_id or host_user_id");
        return response;
    }

    std::string room_id = streaming_server_->create_room(post_id, host_user_id);

    if (room_id.empty()) {
        response.set_error(500, "Failed to create room");
        return response;
    }

    response.status_code = 201;
    response.set_json("{\"room_id\":\"" + room_id + "\",\"post_id\":\"" + post_id + "\"}");
    return response;
}

HttpResponse HttpServer::handle_delete_room(const HttpRequest& req) {
    HttpResponse response;

    auto it = req.path_params.find("room_id");
    if (it == req.path_params.end()) {
        response.set_error(400, "Missing room_id parameter");
        return response;
    }

    std::string room_id = it->second;

    if (!streaming_server_->delete_room(room_id)) {
        response.set_error(404, "Room not found");
        return response;
    }

    response.set_json("{\"status\":\"stopped\",\"room_id\":\"" + room_id + "\"}");
    return response;
}

HttpResponse HttpServer::handle_get_room_stats(const HttpRequest& req) {
    HttpResponse response;

    auto it = req.path_params.find("room_id");
    if (it == req.path_params.end()) {
        response.set_error(400, "Missing room_id parameter");
        return response;
    }

    std::string room_id = it->second;
    Room* room = streaming_server_->get_room(room_id);

    if (!room) {
        response.set_error(404, "Room not found");
        return response;
    }

    std::ostringstream json;
    json << "{";
    json << "\"room_id\":\"" << room->room_id << "\",";
    json << "\"post_id\":\"" << room->post_id << "\",";
    json << "\"is_active\":" << (room->is_active ? "true" : "false") << ",";
    json << "\"viewer_count\":" << room->viewer_count() << ",";
    json << "\"has_host\":" << (room->has_host() ? "true" : "false");
    json << "}";

    response.set_json(json.str());
    return response;
}

HttpResponse HttpServer::handle_get_server_stats(const HttpRequest& req) {
    HttpResponse response;

    auto stats = streaming_server_->get_stats();

    std::ostringstream json;
    json << "{";
    json << "\"total_rooms\":" << stats.total_rooms << ",";
    json << "\"active_rooms\":" << stats.active_rooms << ",";
    json << "\"total_peers\":" << stats.total_peers << ",";
    json << "\"total_viewers\":" << stats.total_viewers << ",";
    json << "\"total_hosts\":" << stats.total_hosts << ",";
    json << "\"total_bytes_sent\":" << stats.total_bytes_sent << ",";
    json << "\"total_bytes_received\":" << stats.total_bytes_received;
    json << "}";

    response.set_json(json.str());
    return response;
}

HttpResponse HttpServer::handle_health_check(const HttpRequest& req) {
    HttpResponse response;
    response.set_json("{\"status\":\"healthy\",\"service\":\"media_server\"}");
    return response;
}

} // namespace onlylang