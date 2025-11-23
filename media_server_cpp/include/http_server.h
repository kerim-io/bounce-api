#ifndef HTTP_SERVER_H
#define HTTP_SERVER_H

#include <string>
#include <memory>
#include <functional>
#include <map>
#include <thread>
#include <atomic>

namespace onlylang {

class RoomManager;
class StreamingServer;

struct HttpRequest {
    std::string method;
    std::string path;
    std::map<std::string, std::string> headers;
    std::string body;
    std::map<std::string, std::string> query_params;
    std::map<std::string, std::string> path_params;
};

struct HttpResponse {
    int status_code;
    std::map<std::string, std::string> headers;
    std::string body;

    HttpResponse() : status_code(200) {
        headers["Content-Type"] = "application/json";
    }

    void set_json(const std::string& json_body) {
        body = json_body;
        headers["Content-Type"] = "application/json";
    }

    void set_error(int code, const std::string& message) {
        status_code = code;
        body = "{\"error\":\"" + message + "\"}";
    }
};

using RouteHandler = std::function<HttpResponse(const HttpRequest&)>;

class HttpServer {
public:
    HttpServer(const std::string& host, int port,
               std::shared_ptr<RoomManager> room_manager,
               std::shared_ptr<StreamingServer> streaming_server);
    ~HttpServer();

    bool start();
    void stop();
    bool is_running() const { return running_; }

    void register_route(const std::string& method, const std::string& path, RouteHandler handler);

private:
    std::string host_;
    int port_;
    std::atomic<bool> running_;
    std::shared_ptr<RoomManager> room_manager_;
    std::shared_ptr<StreamingServer> streaming_server_;

    int server_socket_;
    std::thread accept_thread_;

    std::map<std::string, std::map<std::string, RouteHandler>> routes_;

    void setup_routes();
    void accept_connections();
    void handle_client(int client_socket);

    HttpRequest parse_request(const std::string& raw_request);
    std::string build_response(const HttpResponse& response);

    bool match_route(const std::string& method, const std::string& path,
                     RouteHandler& handler, std::map<std::string, std::string>& params);

    HttpResponse handle_create_room(const HttpRequest& req);
    HttpResponse handle_delete_room(const HttpRequest& req);
    HttpResponse handle_get_room_stats(const HttpRequest& req);
    HttpResponse handle_get_server_stats(const HttpRequest& req);
    HttpResponse handle_health_check(const HttpRequest& req);
};

} // namespace onlylang

#endif // HTTP_SERVER_H